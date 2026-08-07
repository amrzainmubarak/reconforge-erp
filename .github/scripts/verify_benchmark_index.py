"""Verify checked-in benchmark evidence artifacts and their claim boundaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reconforge.benchmark.evidence_index import verify_benchmark_index


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
