"""Parse owned Linux cgroup counters without inventing missing measurements."""
from __future__ import annotations

from typing import Any

PATHS = {
    "cpu": "/sys/fs/cgroup/cpu.stat",
    "memory_current": "/sys/fs/cgroup/memory.current",
    "memory_peak": "/sys/fs/cgroup/memory.peak",
    "io": "/sys/fs/cgroup/io.stat",
    "network": "/proc/net/dev",
}


def parse_counters(raw: dict[str, str]) -> dict[str, Any]:
    """Kernel counters describe this container, including its observer/exec overhead."""
    cpu = {name: int(value) for name, value in (line.split() for line in raw["cpu"].splitlines())}
    io: dict[str, dict[str, int]] = {}
    for line in raw["io"].splitlines():
        device, *values = line.split()
        io[device] = {name: int(value) for name, value in (part.split("=", 1) for part in values)}
    network = {}
    for line in raw["network"].splitlines():
        if ":" not in line:
            continue
        interface, values = line.split(":", 1)
        fields = [int(value) for value in values.split()]
        if len(fields) != 16:
            raise ValueError("Incomplete kernel network counter")
        network[interface.strip()] = {"received_bytes": fields[0], "transmitted_bytes": fields[8]}
    if "usage_usec" not in cpu or not network:
        raise ValueError("Required container counters are missing")
    return {"cpu_microseconds": cpu, "memory_current_bytes": int(raw["memory_current"].strip()),
            "container_lifetime_peak_memory_bytes": int(raw["memory_peak"].strip()),
            "block_io_by_device": io, "network_by_interface": network,
            "scope": "cgroup-v2 container counters; lifetime memory peak includes startup, migration and warmup; exec/observer overhead retained"}
