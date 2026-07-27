from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from reconforge.evidence.binder import read_evidence_index
from reconforge.io.structured import DEFAULT_STRUCTURED_DOCUMENT_POLICY, StructuredDocumentError
from reconforge.reports.client_pack import read_client_pack_manifest

ManifestReader = Callable[[Path | str], object]


def _assert_safe_rejection(
    captured: pytest.ExceptionInfo[ValueError],
    *,
    message: str,
    source: Path,
) -> None:
    assert str(captured.value) == message
    assert source.name not in str(captured.value)
    assert isinstance(captured.value.__cause__, StructuredDocumentError)


@pytest.mark.parametrize(
    ("reader", "filename", "message"),
    [
        (read_client_pack_manifest, "files_manifest.json", "Client pack manifest JSON is invalid"),
        (read_evidence_index, "evidence_index.json", "Evidence index JSON is invalid"),
    ],
    ids=["client-pack", "evidence-index"],
)
@pytest.mark.parametrize(
    "payload",
    [
        '{"schema_version":2,"schema_version":3}',
        '{"value":NaN}',
        '{"value":' + "[" * 65 + "0" + "]" * 65 + "}",
        '{"value":',
    ],
    ids=["duplicate-key", "non-finite", "depth", "malformed"],
)
def test_generated_manifest_readers_reject_ambiguous_or_deep_json_safely(
    tmp_path: Path,
    reader: ManifestReader,
    filename: str,
    message: str,
    payload: str,
) -> None:
    source = tmp_path / filename
    source.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError) as captured:
        reader(source)

    _assert_safe_rejection(captured, message=message, source=source)


@pytest.mark.parametrize(
    ("reader", "filename", "message"),
    [
        (read_client_pack_manifest, "files_manifest.json", "Client pack manifest JSON is invalid"),
        (read_evidence_index, "evidence_index.json", "Evidence index JSON is invalid"),
    ],
    ids=["client-pack", "evidence-index"],
)
def test_generated_manifest_readers_reject_oversized_json_before_parsing(
    tmp_path: Path,
    reader: ManifestReader,
    filename: str,
    message: str,
) -> None:
    source = tmp_path / filename
    source.write_bytes(b" " * (DEFAULT_STRUCTURED_DOCUMENT_POLICY.max_file_bytes + 1))

    with pytest.raises(ValueError) as captured:
        reader(source)

    _assert_safe_rejection(captured, message=message, source=source)
