"""Extract and validate the exact image configuration subject from a Syft SBOM."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def extract_image_config_digest(path: Path) -> str:
    """Return Syft's config digest after validating the image identity envelope."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Syft document must be an object")
    source = document.get("source")
    if not isinstance(source, dict) or source.get("type") != "image":
        raise ValueError("Syft source must be an image")
    metadata = source.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Syft image metadata is missing")
    config_digest = metadata.get("imageID")
    manifest_digest = metadata.get("manifestDigest")
    if not isinstance(config_digest, str) or SHA256.fullmatch(config_digest) is None:
        raise ValueError("Syft image configuration digest is invalid")
    if not isinstance(manifest_digest, str) or SHA256.fullmatch(manifest_digest) is None:
        raise ValueError("Syft image manifest digest is invalid")
    if metadata.get("architecture") != "amd64" or metadata.get("os") != "linux":
        raise ValueError("Syft image platform must be linux/amd64")
    return config_digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--syft-json", type=Path, required=True)
    return parser


def main() -> int:
    try:
        print(extract_image_config_digest(_parser().parse_args().syft_json))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"unable to extract Syft image configuration digest: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
