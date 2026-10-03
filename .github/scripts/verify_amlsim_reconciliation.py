"""Run the pinned AMLSim sample offline and retain exact source/runtime evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reconforge.benchmark.amlsim_reconciliation import (  # noqa: E402
    canonical_digest,
    load_amlsim_profile,
    run_amlsim_reconciliation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "docs/validation/amlsim-workload.v1.yaml")
    parser.add_argument("--input", type=Path, default=ROOT / "tests/fixtures/amlsim/tx.csv")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = load_amlsim_profile(args.profile)
    if args.output.resolve() in {args.input.resolve(), args.profile.resolve()}:
        parser.error("Output must not overwrite an input or profile.")
    with args.input.open("rb") as stream:
        content = stream.read(profile.max_bytes + 1)
    started = datetime.now(UTC).isoformat()
    wall = time.perf_counter()
    cpu = time.process_time()
    tracemalloc.start()
    try:
        report = run_amlsim_reconciliation(content, profile)
        peak_bytes = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    report["execution"] = {
        "started_at": started, "wall_seconds": round(time.perf_counter() - wall, 6),
        "cpu_seconds": round(time.process_time() - cpu, 6), "python_peak_allocated_bytes": peak_bytes,
        "memory_measurement": "tracemalloc Python allocations; not process RSS",
        "python": platform.python_version(), "platform": platform.platform(), "network_calls": 0,
        "source_files": {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()
            for path in (Path(__file__), ROOT / "reconforge/benchmark/amlsim_reconciliation.py", ROOT / "reconforge/reconciliation/deterministic_engine.py")
        },
    }
    report["report_digest"] = canonical_digest(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "input_records": report["input_records"], "matched_pairs": report["matched_pairs"], "reproducibility_digest": report["reproducibility_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
