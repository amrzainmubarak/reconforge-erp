"""Emit the deterministic multi-domain quorum/fencing simulation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reconforge.reliability.ha_dr import build_quorum_simulation_report, verify_quorum_simulation_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_quorum_simulation_report()
    verify_quorum_simulation_report(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
