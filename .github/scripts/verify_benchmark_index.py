"""Verify checked-in benchmark evidence artifacts and their claim boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Prefer the checked-out source tree over a stale editable/non-editable package
# when this repository verification script is invoked directly in CI.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reconforge.benchmark.evidence_index import verify_benchmark_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("docs/execution/benchmarks/INDEX.v1.json"),
    )
    args = parser.parse_args()
    report = verify_benchmark_index(args.index, project_root=args.root)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
