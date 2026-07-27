from __future__ import annotations

from pathlib import Path

import pytest

import reconforge.reports.client_pack as client_pack_module
from reconforge.io.structured import StructuredDocumentError
from reconforge.reports.client_pack import generate_client_pack
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY


def _write_json_source(root: Path, payload: str | bytes) -> Path:
    evidence = root / "evidence"
    evidence.mkdir(parents=True)
    source = evidence / "evidence_index.json"
    if isinstance(payload, bytes):
        source.write_bytes(payload)
    else:
        source.write_text(payload, encoding="utf-8")
    return source


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ('{"private_amount":1,"private_amount":2}', "json_duplicate_key"),
        ('{"private_amount":NaN}', "document_non_finite_number"),
        ('{"private_amount":', "json_structure_invalid"),
        ('{"nested":' * 65 + "1" + "}" * 65, "document_depth_limit"),
        (b'{"private_amount":"\xff"}', "document_encoding_invalid"),
    ],
)
def test_json_redaction_rejects_unsafe_input_before_touching_output(
    tmp_path: Path,
    payload: str | bytes,
    expected_code: str,
) -> None:
    source_root = tmp_path / "source"
    source = _write_json_source(source_root, payload)
    output = tmp_path / "output"

    with pytest.raises(
        ValueError,
        match=r"^Client pack JSON redaction input is invalid$",
    ) as captured:
        generate_client_pack(
            source_root,
            output,
            redact_amounts=True,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    assert source.name not in str(captured.value)
    assert "private_amount" not in str(captured.value)
    assert isinstance(captured.value.__cause__, StructuredDocumentError)
    assert captured.value.__cause__.code == expected_code
    assert not output.exists()


def test_json_redaction_rejects_default_oversize_before_touching_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source = _write_json_source(
        source_root,
        b'{"private_amount":"' + b"7" * (8 * 1024 * 1024) + b'"}',
    )
    output = tmp_path / "output"
    monkeypatch.setattr(
        client_pack_module,
        "_sha256",
        lambda _path: pytest.fail("oversized JSON reached fingerprint hashing"),
    )

    with pytest.raises(ValueError) as captured:
        generate_client_pack(
            source_root,
            output,
            redact_amounts=True,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    assert str(captured.value) == "Client pack JSON redaction input is invalid"
    assert source.name not in str(captured.value)
    assert isinstance(captured.value.__cause__, StructuredDocumentError)
    assert captured.value.__cause__.code == "document_size_limit"
    assert not output.exists()
