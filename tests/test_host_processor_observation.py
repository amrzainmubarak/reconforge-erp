"""Deterministic native-boundary and sampler tests; no host counters or workloads."""

from __future__ import annotations

import ctypes
from datetime import UTC, datetime
from typing import Any

import pytest

from reconforge.benchmark import host_processor_observation as host
from reconforge.benchmark import resource_sampling as sampling


class Clock:
    value = 10.0

    def __call__(self) -> float:
        return self.value


class Backend:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.open_status = 0
        self.add_status: dict[str, int] = {}
        self.collect_status = 0
        self.values = {"processor_performance_percent": (0, 0, 125.5),
                       "processor_frequency_mhz": (0, 1, 3456.0)}
        self.power: tuple[bool, int | None, dict[str, int] | None] = (True, None, {
            "ACLineStatus": 1, "BatteryFlag": 8, "BatteryLifePercent": 98, "SystemStatusFlag": 0,
            "BatteryLifeTime": 0xFFFFFFFF, "BatteryFullLifeTime": 7200})
        self.raise_at: str | None = None
        self.close_status = 0

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if name == self.raise_at:
            raise OSError("secret-host-path")

    def open_query(self) -> int:
        self._call("open")
        return self.open_status

    def add_counter(self, name: str, path: str) -> int:
        self._call(f"add:{name}")
        assert path == host.COUNTER_PATHS[name]
        return self.add_status.get(name, 0)

    def collect(self) -> int:
        self._call("collect")
        return self.collect_status

    def formatted(self, name: str) -> tuple[int, int, float]:
        self._call(f"format:{name}")
        return self.values[name]

    def power_status(self) -> tuple[bool, int | None, dict[str, int] | None]:
        self._call("power")
        return self.power

    def close(self) -> int:
        self._call("close")
        return self.close_status


def observer(backend: Backend, clock: Clock) -> host.WindowsProcessorObservation:
    return host.WindowsProcessorObservation(platform_name="win32", backend=backend, monotonic=clock,
                                            utc_clock=lambda: datetime(2026, 10, 10, tzinfo=UTC))


def test_priming_minimum_interval_and_uncapped_turbo_with_raw_power() -> None:
    backend, clock = Backend(), Clock()
    observed = observer(backend, clock)
    first = observed.observe()
    assert first["status"] == "priming"
    assert first["processor_performance_percent"] is first["processor_frequency_mhz"] is None
    assert not any(call.startswith("format:") for call in backend.calls)
    clock.value += .99
    too_soon = observed.observe()
    assert too_soon["status"] == "priming" and too_soon["reason"] == "minimum_collection_interval"
    assert backend.calls.count("collect") == 1
    clock.value += .01
    result = observed.observe()
    assert result["status"] == "available"
    assert result["processor_performance_percent"] == 125.5
    assert result["processor_frequency_mhz"] == 3456.0
    assert result["monotonic_seconds"] == 11 and result["measurement_seconds"] == 0
    assert result["observed_at_utc"] == "2026-10-10T00:00:00+00:00"
    assert result["power"]["raw"]["ACLineStatus"] == 1
    assert result["power"]["ac_online"] is True
    assert result["power"]["battery_life_seconds"] is None
    assert result["power"]["battery_full_life_seconds"] == 7200
    assert observed.close() == {"status": "closed", "api_status": 0}
    assert observed.close() == {"status": "closed", "api_status": 0}
    calls = list(backend.calls)
    assert observed.observe()["status"] == "closed" and backend.calls == calls
    assert backend.calls.count("close") == 1


@pytest.mark.parametrize("api_status,cstatus,value", [
    (0x800007D0, 0, 100.0), (0, 0xC0000BC6, 100.0), (0, 0, float("nan")),
    (0, 1, float("inf")), (0, 0, -1.0),
])
def test_invalid_counter_result_never_becomes_fabricated_zero(api_status: int, cstatus: int, value: float) -> None:
    backend, clock = Backend(), Clock()
    backend.values["processor_performance_percent"] = (api_status, cstatus, value)
    observed = observer(backend, clock)
    observed.observe()
    clock.value += 1
    result = observed.observe()
    assert result["status"] == "partial"
    assert result["processor_performance_percent"] is None
    assert result["processor_frequency_mhz"] == 3456.0
    assert result["counters"]["processor_performance_percent"]["api_status"] == api_status
    assert result["counters"]["processor_performance_percent"]["cstatus"] == cstatus
    observed.close()


def test_missing_counter_is_explicit_and_surviving_counter_remains_available() -> None:
    backend, clock = Backend(), Clock()
    backend.add_status["processor_frequency_mhz"] = 0xC0000BB8
    observed = observer(backend, clock)
    observed.observe()
    clock.value += 1
    result = observed.observe()
    assert result["status"] == "partial" and result["processor_performance_percent"] == 125.5
    assert result["processor_frequency_mhz"] is None
    assert result["counters"]["processor_frequency_mhz"]["api_status"] == 0xC0000BB8
    assert "format:processor_frequency_mhz" not in backend.calls
    observed.close()


def test_unknown_power_sentinels_and_actual_zero_are_distinct() -> None:
    backend, clock = Backend(), Clock()
    backend.power = True, None, {"ACLineStatus": 255, "BatteryFlag": 255, "BatteryLifePercent": 255,
        "SystemStatusFlag": 255, "BatteryLifeTime": 0xFFFFFFFF, "BatteryFullLifeTime": 0xFFFFFFFF}
    observed = observer(backend, clock)
    power = observed.observe()["power"]
    assert power["status"] == "available" and power["raw"]["BatteryLifePercent"] == 255
    assert all(power[key] is None for key in ("ac_online", "battery_flags", "battery_percent",
        "battery_saver_on", "battery_life_seconds", "battery_full_life_seconds"))
    backend.power = True, None, {"ACLineStatus": 0, "BatteryFlag": 128, "BatteryLifePercent": 0,
        "SystemStatusFlag": 0, "BatteryLifeTime": 0, "BatteryFullLifeTime": 0}
    power = observed.observe()["power"]
    assert power["ac_online"] is False and power["battery_flags"] == 128
    assert power["battery_percent"] == power["battery_life_seconds"] == 0
    observed.close()


def test_failed_collection_requires_new_priming_and_power_failure_retains_error() -> None:
    backend, clock = Backend(), Clock()
    observed = observer(backend, clock)
    observed.observe()
    clock.value += 1
    backend.collect_status = 0x800007D5
    backend.power = False, 5, None
    failed = observed.observe()
    assert failed["status"] == "unavailable" and failed["collect_api_status"] == 0x800007D5
    assert failed["processor_performance_percent"] is None
    assert failed["power"]["win32_error"] == 5 and failed["power"]["ac_online"] is None
    backend.collect_status = 0
    clock.value += 1
    assert observed.observe()["status"] == "priming"
    clock.value += 1
    assert observed.observe()["status"] == "partial"  # CPU available, power remains unavailable.
    observed.close()


@pytest.mark.parametrize("stage", ["open", "add:processor_frequency_mhz"])
def test_initialization_exception_closes_query_and_redacts_message(stage: str) -> None:
    backend, clock = Backend(), Clock()
    backend.raise_at = stage
    observed = observer(backend, clock)
    result = observed.observe()
    assert result["status"] == "unavailable" and result["initialization"]["exception_type"] == "OSError"
    assert "secret-host-path" not in str(result)
    assert backend.calls.count("close") == 1
    observed.close()
    assert backend.calls.count("close") == 1


def test_open_error_and_close_error_codes_are_retained() -> None:
    backend, clock = Backend(), Clock()
    backend.open_status, backend.close_status = 0xC0000BC0, 0xC0000BBC
    observed = observer(backend, clock)
    result = observed.observe()
    assert result["initialization"]["api_status"] == 0xC0000BC0
    assert observed.close() == {"status": "close_failed", "api_status": 0xC0000BBC}
    assert backend.calls == ["open", "close"]


def test_close_exception_is_nonfatal_idempotent_and_redacted() -> None:
    backend, clock = Backend(), Clock()
    observed = observer(backend, clock)
    backend.raise_at = "close"
    result = observed.close()
    assert result == {"status": "close_failed", "api_status": None, "exception_type": "OSError"}
    assert observed.close() == result and backend.calls.count("close") == 1


def test_unsupported_platform_never_calls_native_backend() -> None:
    backend = Backend()
    observed = host.WindowsProcessorObservation(platform_name="linux", backend=backend)
    result = observed.observe()
    assert result["status"] == "unsupported_platform"
    assert result["processor_performance_percent"] is result["processor_frequency_mhz"] is None
    assert result["power"]["ac_online"] is None
    assert observed.close()["status"] == "not_opened" and backend.calls == []


def test_windows_ctypes_layout_and_language_neutral_native_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[Any, ...]]] = []
    power_available = [True]

    class NativeFunction:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, *args: Any) -> int:
            calls.append((self.name, args))
            if self.name in ("PdhOpenQueryW", "PdhAddEnglishCounterW"):
                ctypes.cast(args[-1], ctypes.POINTER(ctypes.c_void_p))[0] = 42
            if self.name == "PdhGetFormattedCounterValue":
                value = ctypes.cast(args[-1], ctypes.POINTER(host._CounterValue)).contents
                value.CStatus, value.value.doubleValue = 1, 135.25
            if self.name == "GetSystemPowerStatus":
                ctypes.cast(args[0], ctypes.POINTER(host._PowerStatus)).contents.ACLineStatus = 1
                return int(power_available[0])
            return 0

    class Library:
        def __getattr__(self, name: str) -> NativeFunction:
            value = NativeFunction(name)
            setattr(self, name, value)
            return value

    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: Library(), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    assert ctypes.sizeof(host._PowerStatus) == 12
    assert host._CounterValue.value.offset == 8 and ctypes.sizeof(host._CounterValue) == 16
    backend = host._NativeWindowsBackend()
    assert backend.open_query() == 0
    assert backend.add_counter("test", host.COUNTER_PATHS["processor_performance_percent"]) == 0
    assert backend.collect() == 0
    assert backend.formatted("test") == (0, 1, 135.25)
    assert backend.power_status()[2]["ACLineStatus"] == 1
    power_available[0] = False
    assert backend.power_status() == (False, 5, None)
    assert backend.close() == backend.close() == 0
    assert [name for name, _ in calls].count("PdhCloseQuery") == 1
    args = next(args for name, args in calls if name == "PdhGetFormattedCounterValue")
    # Independently pinned from the official WinSDK Pdh.h, not the production constant.
    assert args[1] == 0x8200  # DOUBLE | NOCAP100, not an implicit 100% cap.
    assert backend.pdh.PdhOpenQueryW.restype is ctypes.c_uint32


@pytest.mark.parametrize("platform,enabled", [("linux", True), ("win32", False)])
def test_sampler_disabling_or_unsupported_platform_has_no_native_calls(
    monkeypatch: pytest.MonkeyPatch, platform: str, enabled: bool,
) -> None:
    monkeypatch.setattr(sampling.sys, "platform", platform)
    monkeypatch.setattr(sampling, "WindowsProcessorObservation", lambda: pytest.fail("native observation forbidden"))
    monkeypatch.setattr(sampling, "process_memory", lambda: {"rss_bytes": 17})
    sampler = sampling.ResourceSampler(lambda: {"value": 4}, max_samples=1, observe_host_processor=enabled)
    monkeypatch.setattr(sampler._stop, "wait", lambda _seconds: False)
    sampler._run()
    report = sampler.stop()
    assert report["status"] == "complete" and report["raw_samples"][0]["host_processor"] is None
    assert report["host_processor_observation"]["status"] == ("unsupported_platform" if enabled else "disabled")


@pytest.mark.parametrize("failure", ["none", "callback", "host"])
def test_sampler_single_observer_closes_even_on_failures_without_corrupting_business_row(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    calls: list[str] = []

    class Observer:
        def __init__(self) -> None:
            calls.append("init")

        def observe(self) -> dict[str, Any]:
            calls.append("observe")
            if failure == "host":
                raise OSError("secret-native-message")
            return {"status": "priming", "processor_frequency_mhz": None}

        def close(self) -> dict[str, Any]:
            calls.append("close")
            return {"status": "closed", "api_status": 0}

    def callback() -> dict[str, Any]:
        if failure == "callback":
            raise ValueError("secret-connection")
        return {"financial_oracle": "493671004", "host_processor": "override-attempt"}

    monkeypatch.setattr(sampling.sys, "platform", "win32")
    monkeypatch.setattr(sampling, "WindowsProcessorObservation", Observer)
    monkeypatch.setattr(sampling, "process_memory", lambda: {"rss_bytes": 17})
    sampler = sampling.ResourceSampler(callback, max_samples=1)
    monkeypatch.setattr(sampler._stop, "wait", lambda _seconds: False)
    sampler._run()
    report = sampler.stop()
    assert calls == ["init", "observe", "close"]
    assert report["host_processor_observation"]["cleanup"]["status"] == "closed"
    assert "secret-" not in str(report)
    if failure == "callback":
        assert report["status"] == "incomplete" and report["errors"][0]["exception_type"] == "ValueError"
        assert report["errors"][0]["host_processor"]["status"] == "priming"
    else:
        assert report["status"] == "complete"
        assert report["raw_samples"][0]["financial_oracle"] == "493671004"
        assert report["raw_samples"][0]["host_processor"]["status"] == ("unavailable" if failure == "host" else "priming")


def test_sampler_rejects_implicit_observation_switch() -> None:
    with pytest.raises(ValueError, match="explicit boolean"):
        sampling.ResourceSampler(lambda: {}, observe_host_processor=1)  # type: ignore[arg-type]


def test_native_library_load_failure_is_explicit_without_host_disclosure(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> None:
        raise OSError("secret-installation-path")

    monkeypatch.setattr(host, "_NativeWindowsBackend", unavailable)
    observed = host.WindowsProcessorObservation(platform_name="win32")
    result = observed.observe()
    assert result["status"] == "unavailable" and result["processor_frequency_mhz"] is None
    assert result["initialization"]["stage"] == "load_libraries"
    assert result["initialization"]["measurement_seconds"] >= 0
    assert "secret-" not in str(result)
    assert observed.close()["status"] == "not_opened"


def test_missing_windows_ctypes_exports_are_unavailable_and_never_used_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(ctypes, "WinDLL", raising=False)
    monkeypatch.delattr(ctypes, "get_last_error", raising=False)
    linux = host.WindowsProcessorObservation(platform_name="linux")
    assert linux.observe()["status"] == "unsupported_platform"
    assert linux.close()["status"] == "not_opened"
    windows = host.WindowsProcessorObservation(platform_name="win32")
    result = windows.observe()
    assert result["status"] == "unavailable" and result["processor_frequency_mhz"] is None
    assert result["initialization"]["stage"] == "load_libraries"
    assert result["initialization"]["exception_type"] == "OSError"
    assert windows.close()["status"] == "not_opened"


def test_sampler_optional_constructor_failure_preserves_financial_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> None:
        raise OSError("secret-installation-path")

    monkeypatch.setattr(sampling.sys, "platform", "win32")
    monkeypatch.setattr(sampling, "WindowsProcessorObservation", unavailable)
    monkeypatch.setattr(sampling, "process_memory", lambda: {"rss_bytes": 17})
    sampler = sampling.ResourceSampler(lambda: {"financial_oracle": "493671004"}, max_samples=1)
    monkeypatch.setattr(sampler._stop, "wait", lambda _seconds: False)
    sampler._run()
    result = sampler.stop()
    assert result["status"] == "complete" and result["raw_samples"][0]["financial_oracle"] == "493671004"
    assert result["host_processor_observation"]["status"] == "unavailable"
    assert result["host_processor_observation"]["exception_type"] == "OSError"
    assert "secret-" not in str(result)
