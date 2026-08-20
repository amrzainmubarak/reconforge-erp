#!/usr/bin/env python3
"""Guardrail to enforce publication freeze from execution decisions."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail a release workflow if publication freeze is active."
    )
    parser.add_argument(
        "--decisions",
        default="docs/execution/DECISIONS.md",
        help="Path to the Decisions execution log.",
    )
    parser.add_argument(
        "--decision-id",
        default="D-485",
        help="Decision ID that defers publication.",
    )
    return parser.parse_args()


def is_freeze_active(decisions_path: Path, decision_id: str) -> bool:
    if not decisions_path.exists():
        return True

    text = decisions_path.read_text(encoding="utf-8")
    marker = re.compile(rf"^###\s+{re.escape(decision_id)}\b", re.MULTILINE)
    match = marker.search(text)
    if match is None:
        return True

    # Decisions remain append-only evidence.  A heading therefore continues to
    # block publication unless its own section contains an explicit closure
    # marker.  Ambiguous or malformed status text stays fail-closed.
    next_heading = re.search(r"^###\s+\S", text[match.end() :], re.MULTILINE)
    section_end = match.end() + next_heading.start() if next_heading else len(text)
    section = text[match.start() : section_end]
    closed = re.search(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?status(?:\*\*)?\s*:\s*"
        r"(?:closed|complete|completed|resolved)\s*$",
        section,
        re.IGNORECASE | re.MULTILINE,
    )
    return closed is None


def main() -> int:
    args = parse_args()
    decisions_path = Path(args.decisions)

    if is_freeze_active(decisions_path, args.decision_id):
        print(
            f"Publication freeze is active via {args.decision_id} in {decisions_path}.",
        )
        print(
            "Please keep release publishing blocked until the owner removes/ closes this decision.",
        )
        return 1

    print(f"Publication freeze decision {args.decision_id} is explicitly closed; release gating may proceed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
