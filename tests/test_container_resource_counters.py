"""Real cgroup-v2 shape and refusal of missing counter evidence."""
import pytest

from reconforge.benchmark.container_resource_counters import parse_counters


def test_cpu_io_and_network_boundaries_remain_exact_integer_counters() -> None:
    raw = {"cpu": "usage_usec 1200123\nuser_usec 1000000\nsystem_usec 200123\n",
           "memory_current": "16777216\n", "memory_peak": "33554432\n",
           "io": "8:48 rbytes=23957504 wbytes=4096 rios=50 wios=1 dbytes=0 dios=0\n",
           "network": "Inter-| Receive | Transmit\nlo: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\neth0: 13620 304 0 0 0 0 0 0 126 3 0 0 0 0 0 0\n"}
    measured = parse_counters(raw)
    assert measured["cpu_microseconds"]["usage_usec"] == 1200123
    assert measured["container_lifetime_peak_memory_bytes"] == 33554432
    assert measured["block_io_by_device"]["8:48"]["wbytes"] == 4096
    assert measured["network_by_interface"]["eth0"] == {"received_bytes": 13620, "transmitted_bytes": 126}
    raw["cpu"] = "user_usec 1000000\n"
    with pytest.raises(ValueError, match="missing"):
        parse_counters(raw)
