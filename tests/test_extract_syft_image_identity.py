from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "extract_syft_image_config_digest.py"
CONFIG_DIGEST = "sha256:" + "a" * 64
MANIFEST_DIGEST = "sha256:" + "b" * 64


def _document() -> dict[str, object]:
    return {
        "source": {
            "type": "image",
            "metadata": {
                "imageID": CONFIG_DIGEST,
                "manifestDigest": MANIFEST_DIGEST,
                "architecture": "amd64",
                "os": "linux",
            },
        }
    }


def test_extracts_the_syft_config_digest_from_a_valid_linux_image(tmp_path: Path) -> None:
    path = tmp_path / "image.syft.json"
    path.write_text(json.dumps(_document()), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--syft-json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == CONFIG_DIGEST
    assert result.stderr == ""


def test_rejects_invalid_or_wrong_platform_syft_identity(tmp_path: Path) -> None:
    document = _document()
    metadata = document["source"]["metadata"]  # type: ignore[index]
    assert isinstance(metadata, dict)
    metadata["architecture"] = "arm64"
    path = tmp_path / "image.syft.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--syft-json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "linux/amd64" in result.stderr
