"""Optional Windows host observations; no power changes, subprocesses, or business effects.

PDH rates need a priming collection followed by a collection at least one second
later. Values are observational engineering floats, never financial inputs.
"""

from __future__ import annotations

import ctypes
import math
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

COUNTER_PATHS = {
    "processor_performance_percent": r"\Processor Information(_Total)\% Processor Performance",
    "processor_frequency_mhz": r"\Processor Information(_Total)\Processor Frequency",
}
# WinSDK Pdh.h: PDH_FMT_DOUBLE=0x00000200, PDH_FMT_NOCAP100=0x00008000.
PDH_FMT_DOUBLE_NOCAP100 = 0x00000200 | 0x00008000
MINIMUM_COLLECTION_SECONDS = 1.0


class _CounterUnion(ctypes.Union):
    _fields_ = [("doubleValue", ctypes.c_double), ("longValue", ctypes.c_int32),
                ("largeValue", ctypes.c_int64), ("AnsiStringValue", ctypes.c_char_p),
                ("WideStringValue", ctypes.c_wchar_p)]


class _CounterValue(ctypes.Structure):
    _fields_ = [("CStatus", ctypes.c_uint32), ("value", _CounterUnion)]


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_uint32), ("BatteryFullLifeTime", ctypes.c_uint32)]


class ProcessorObservationBackend(Protocol):
    """Small native boundary to allow deterministic tests without touching the host."""

    def open_query(self) -> int: ...
    def add_counter(self, name: str, path: str) -> int: ...
    def collect(self) -> int: ...
    def formatted(self, name: str) -> tuple[int, int, float]: ...
    def power_status(self) -> tuple[bool, int | None, dict[str, int] | None]: ...
    def close(self) -> int: ...


class _NativeWindowsBackend:
    def __init__(self) -> None:
        self.pdh = ctypes.WinDLL("pdh", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        self.pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_size_t,
                                                  ctypes.POINTER(ctypes.c_void_p)]
        self.pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        self.pdh.PdhGetFormattedCounterValue.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(_CounterValue)]
        self.pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        for name in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData",
                     "PdhGetFormattedCounterValue", "PdhCloseQuery"):
            getattr(self.pdh, name).restype = ctypes.c_uint32
        self.kernel.GetSystemPowerStatus.argtypes = [ctypes.POINTER(_PowerStatus)]
        self.kernel.GetSystemPowerStatus.restype = ctypes.c_int32
        self.query = ctypes.c_void_p()
        self.counters: dict[str, ctypes.c_void_p] = {}

    def open_query(self) -> int:
        return int(self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)))

    def add_counter(self, name: str, path: str) -> int:
        handle = ctypes.c_void_p()
        status = int(self.pdh.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(handle)))
        if status == 0:
            self.counters[name] = handle
        return status

    def collect(self) -> int:
        return int(self.pdh.PdhCollectQueryData(self.query))

    def formatted(self, name: str) -> tuple[int, int, float]:
        value = _CounterValue()
        status = int(self.pdh.PdhGetFormattedCounterValue(self.counters[name], PDH_FMT_DOUBLE_NOCAP100,
                                                         None, ctypes.byref(value)))
        return status, int(value.CStatus), float(value.value.doubleValue)

    def power_status(self) -> tuple[bool, int | None, dict[str, int] | None]:
        value = _PowerStatus()
        if not self.kernel.GetSystemPowerStatus(ctypes.byref(value)):
            return False, ctypes.get_last_error(), None
        return True, None, {field[0]: int(getattr(value, field[0])) for field in _PowerStatus._fields_}

    def close(self) -> int:
        if not self.query.value:
            return 0
        handle, self.query = self.query, ctypes.c_void_p()
        self.counters.clear()
        return int(self.pdh.PdhCloseQuery(handle))


def _unavailable_power() -> dict[str, Any]:
    return {"status": "unavailable", "win32_error": None, "raw": None,
            "ac_online": None, "battery_flags": None, "battery_percent": None,
            "battery_saver_on": None, "battery_life_seconds": None, "battery_full_life_seconds": None}


def _power_observation(backend: ProcessorObservationBackend) -> dict[str, Any]:
    available, error, raw = backend.power_status()
    if not available or raw is None:
        return {**_unavailable_power(), "win32_error": error}
    return {"status": "available", "win32_error": None, "raw": raw,
            "ac_online": bool(raw["ACLineStatus"]) if raw["ACLineStatus"] in (0, 1) else None,
            "battery_flags": raw["BatteryFlag"] if raw["BatteryFlag"] != 255 else None,
            "battery_percent": raw["BatteryLifePercent"] if 0 <= raw["BatteryLifePercent"] <= 100 else None,
            "battery_saver_on": bool(raw["SystemStatusFlag"]) if raw["SystemStatusFlag"] in (0, 1) else None,
            "battery_life_seconds": raw["BatteryLifeTime"] if raw["BatteryLifeTime"] != 0xFFFFFFFF else None,
            "battery_full_life_seconds": raw["BatteryFullLifeTime"] if raw["BatteryFullLifeTime"] != 0xFFFFFFFF else None}


class WindowsProcessorObservation:
    """One query per sampler, explicit unavailable values, and idempotent cleanup.

    English counter names are language-neutral. NOCAP100 preserves reported turbo
    performance above 100%. These host-wide samples do not attribute CPU time to a
    workload, measure temperature, or establish historical throttling causation.
    """

    def __init__(self, *, platform_name: str | None = None,
                 backend: ProcessorObservationBackend | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 utc_clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.platform = sys.platform if platform_name is None else platform_name
        self._monotonic, self._utc_clock = monotonic, utc_clock
        self._backend: ProcessorObservationBackend | None = None
        self._last_collection: float | None = None
        self._closed = False
        self._cleanup: dict[str, Any] | None = None
        self._initialization: dict[str, Any] = {"status": "unsupported_platform"}
        self._counter_states: dict[str, dict[str, Any]] = {
            name: {"path": path, "status": "unavailable", "api_status": None, "cstatus": None}
            for name, path in COUNTER_PATHS.items()}
        if self.platform != "win32":
            return
        initialization_begin = self._monotonic()
        stage = "load_libraries"
        try:
            self._backend = backend if backend is not None else _NativeWindowsBackend()
            stage = "open_query"
            result = self._backend.open_query()
            if result != 0:
                self._initialization = {"status": "unavailable", "stage": stage, "api_status": result}
                self._release_backend()
                return
            stage = "add_counters"
            for name, path in COUNTER_PATHS.items():
                result = self._backend.add_counter(name, path)
                self._counter_states[name].update(status="ready" if result == 0 else "unavailable", api_status=result)
            self._initialization = {"status": "ready", "api_status": 0}
        except Exception as exc:
            # Exception text can include environment-specific paths. Retain only stage/type.
            self._initialization = {"status": "unavailable", "stage": stage, "exception_type": type(exc).__name__}
            self._release_backend()
        finally:
            self._initialization["measurement_seconds"] = self._monotonic() - initialization_begin

    def _release_backend(self) -> None:
        backend, self._backend = self._backend, None
        if backend is None:
            self._cleanup = {"status": "not_opened", "api_status": None}
            return
        try:
            result = backend.close()
            self._cleanup = {"status": "closed" if result == 0 else "close_failed", "api_status": result}
        except Exception as exc:
            self._cleanup = {"status": "close_failed", "api_status": None, "exception_type": type(exc).__name__}

    def observe(self) -> dict[str, Any]:
        begin = self._monotonic()
        row: dict[str, Any] = {
            "status": "closed" if self._closed else self._initialization["status"],
            "observed_at_utc": self._utc_clock().isoformat(), "monotonic_seconds": begin,
            "processor_performance_percent": None, "processor_frequency_mhz": None,
            "initialization": dict(self._initialization),
            "counters": {name: dict(state) for name, state in self._counter_states.items()},
            "power": _unavailable_power(), "collect_api_status": None,
            "minimum_collection_seconds": MINIMUM_COLLECTION_SECONDS,
        }
        backend = None if self._closed else self._backend
        if backend is not None:
            try:
                row["power"] = _power_observation(backend)
            except Exception as exc:
                row["power"] = {**_unavailable_power(), "exception_type": type(exc).__name__}
            try:
                self._collect(row, backend)
            except Exception as exc:
                self._last_collection = None
                row.update(status="unavailable", exception_type=type(exc).__name__)
            if row["status"] == "available" and row["power"]["status"] != "available":
                row["status"] = "partial"
        row["measurement_seconds"] = self._monotonic() - begin
        return row

    def _collect(self, row: dict[str, Any], backend: ProcessorObservationBackend) -> None:
        ready = [name for name, state in self._counter_states.items() if state["status"] == "ready"]
        if not ready:
            row["status"] = "unavailable"
            return
        now = self._monotonic()
        if self._last_collection is not None and now - self._last_collection < MINIMUM_COLLECTION_SECONDS:
            row.update(status="priming", reason="minimum_collection_interval")
            for name in ready:
                row["counters"][name]["status"] = "priming"
            return
        previous = self._last_collection
        result = backend.collect()
        row["collect_api_status"] = result
        if result != 0:
            self._last_collection = None
            row.update(status="unavailable", reason="collection_failed")
            return
        self._last_collection = self._monotonic()
        row["collection_monotonic_seconds"] = self._last_collection
        row["previous_collection_monotonic_seconds"] = previous
        if previous is None:
            row["status"] = "priming"
            for name in ready:
                row["counters"][name]["status"] = "priming"
            return
        available = 0
        for name in ready:
            state = row["counters"][name]
            try:
                result, cstatus, value = backend.formatted(name)
                state.update(api_status=result, cstatus=cstatus, status="unavailable")
                if result == 0 and cstatus in (0, 1) and math.isfinite(value) and value >= 0:
                    row[name] = value
                    state["status"] = "available"
                    available += 1
                elif result == 0 and cstatus in (0, 1):
                    state["reason"] = "invalid_numeric_value"
            except Exception as exc:
                state.update(status="unavailable", exception_type=type(exc).__name__)
        row["status"] = "available" if available == len(COUNTER_PATHS) else "partial" if available else "unavailable"

    def close(self) -> dict[str, Any]:
        if not self._closed:
            self._closed = True
            if self._backend is not None or self._cleanup is None:
                self._release_backend()
        return dict(self._cleanup or {"status": "not_opened", "api_status": None})
