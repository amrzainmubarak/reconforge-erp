"""Bounded observational sampling for reproducible benchmarks, without business effects."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from reconforge.benchmark.host_processor_observation import WindowsProcessorObservation


def process_memory() -> dict[str, int | str]:
    """Expose the actual platform's process counters with their measurement scope."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        library = ctypes.WinDLL("psapi", use_last_error=True)
        library.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        library.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not library.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "Process memory measurement failed")
        return {"rss_bytes": counters.WorkingSetSize, "process_lifetime_peak_rss_bytes": counters.PeakWorkingSetSize,
                "scope": "Windows process working set; lifetime peak begins before benchmark admission"}
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"process_lifetime_peak_rss_bytes": int(peak * (1 if sys.platform == "darwin" else 1024)),
            "scope": "getrusage process lifetime peak; not a sampled current RSS"}


class ResourceSampler:
    """Sample a read-only callback; retain bounded raw samples and explicit failures."""

    def __init__(self, observe: Callable[[], dict[str, Any]], *, interval_seconds: float = 10,
                 max_samples: int = 1000, observe_host_processor: bool = True) -> None:
        if not 1 <= interval_seconds <= 60 or type(max_samples) is not int or not 1 <= max_samples <= 10000:
            raise ValueError("Resource sampler requires a bounded interval and sample count")
        self.observe = observe
        if type(observe_host_processor) is not bool:
            raise ValueError("Host processor observation must be an explicit boolean")
        self.observe_host_processor = observe_host_processor
        self._host_processor: dict[str, Any] = {"requested": observe_host_processor, "platform": sys.platform,
            "status": "not_started" if observe_host_processor and sys.platform == "win32" else
                      "unsupported_platform" if observe_host_processor else "disabled",
            "cleanup": None,
            "scope": "host-wide PDH/power observations; no temperature or historical cause attribution"}
        self.interval_seconds = interval_seconds
        self.max_samples = max_samples
        self.samples: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("A benchmark sampler can start only once")
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="benchmark-resource-sampler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        host: WindowsProcessorObservation | None = None
        try:
            if self.observe_host_processor and sys.platform == "win32":
                try:
                    host = WindowsProcessorObservation()
                    self._host_processor["status"] = "enabled"
                except Exception as exc:
                    self._host_processor.update(status="unavailable", exception_type=type(exc).__name__)
            while not self._stop.is_set() and len(self.samples) + len(self.errors) < self.max_samples:
                begin = time.monotonic()
                observation: dict[str, Any] | None = None
                if host is not None:
                    try:
                        observation = host.observe()
                    except Exception as exc:
                        observation = {"status": "unavailable", "processor_performance_percent": None,
                                       "processor_frequency_mhz": None, "exception_type": type(exc).__name__}
                try:
                    row = self.observe()
                    self.samples.append({"elapsed_seconds": begin - self._started,
                        "measurement_seconds": time.monotonic() - begin, "client_cpu_seconds": time.process_time(),
                        "client_pid": os.getpid(), "client_memory": process_memory(), **row,
                        "host_processor": observation})
                except Exception as exc:
                    # Exception text may contain connection credentials. Retain type/time, never a DSN.
                    self.errors.append({"elapsed_seconds": begin - self._started, "exception_type": type(exc).__name__,
                                        "host_processor": observation})
                self._stop.wait(max(0, self.interval_seconds - (time.monotonic() - begin)))
        finally:
            if host is not None:
                self._host_processor["cleanup"] = host.close()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
        running = self._thread is not None and self._thread.is_alive()
        return {"interval_seconds": self.interval_seconds, "max_samples": self.max_samples,
                "status": "incomplete" if running or self.errors or not self.samples else "complete",
                "thread_still_running": running, "raw_samples": list(self.samples), "errors": list(self.errors),
                "host_processor_observation": dict(self._host_processor),
                "scope": "sampled peaks can miss shorter spikes; client lifetime RSS differs from Python allocation peak"}
