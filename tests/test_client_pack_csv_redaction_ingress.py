from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

import reconforge.reports.client_pack as client_pack_module
from reconforge.io.ingress import FileIngressError
from reconforge.reports.client_pack import ClientPackOptions, generate_client_pack
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
)


def _write_csv_source(root: Path, payload: str | bytes) -> Path:
    evidence = root / "evidence"
    evidence.mkdir(parents=True)
    source = evidence / "source_records.csv"
    if isinstance(payload, bytes):
        source.write_bytes(payload)
    else:
        source.write_text(payload, encoding="utf-8", newline="")
    return source


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"", "file_empty"),
        ("name,total_amount\nprivate-name\n", "csv_shape_invalid"),
        (b"name,total_amount\nprivate-name,\xff\n", "csv_structure_invalid"),
        ("total_amount,total_amount\n1,2\n", "csv_header_duplicate"),
        (b"PK\x03\x04not-a-csv", "file_content_type_mismatch"),
        ("name\n" + "x" * 128_001 + "\n", "csv_field_limit"),
    ],
    ids=["empty", "shape", "encoding", "duplicate", "content-mismatch", "field-limit"],
)
def test_csv_redaction_rejects_unsafe_input_before_touching_output(
    tmp_path: Path,
    payload: str | bytes,
    expected_code: str,
) -> None:
    source_root = tmp_path / "source"
    source = _write_csv_source(source_root, payload)
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "existing-private-output.txt"
    sentinel.write_text("must-remain", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"^Client pack CSV redaction input is invalid$",
    ) as captured:
        generate_client_pack(
            source_root,
            output,
            redact_amounts=True,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    assert source.name not in str(captured.value)
    assert "private-name" not in str(captured.value)
    assert isinstance(captured.value.__cause__, FileIngressError)
    assert captured.value.__cause__.code == expected_code
    assert sentinel.read_text(encoding="utf-8") == "must-remain"


def test_csv_redaction_rejects_default_oversize_before_hashing_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source = _write_csv_source(source_root, b"name,total_amount\n")
    with source.open("r+b") as handle:
        handle.seek(64 * 1024 * 1024)
        handle.write(b"x")
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "existing-private-output.txt"
    sentinel.write_text("must-remain", encoding="utf-8")
    monkeypatch.setattr(
        client_pack_module,
        "_sha256",
        lambda _path: pytest.fail("oversized CSV reached fingerprint hashing"),
    )

    with pytest.raises(ValueError) as captured:
        generate_client_pack(
            source_root,
            output,
            redact_amounts=True,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    assert str(captured.value) == "Client pack CSV redaction input is invalid"
    assert isinstance(captured.value.__cause__, FileIngressError)
    assert captured.value.__cause__.code == "file_size_limit"
    assert sentinel.read_text(encoding="utf-8") == "must-remain"


def test_csv_redaction_preserves_valid_field_text_and_policy_buckets(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_csv_source(
        source_root,
        'customer_name,total_amount,note\n"Private, Name",99.999999999999999999,"line one\nline two"\n',
    )

    for policy, folder in (
        (STRICT_FINANCIAL_INPUT_POLICY, "strict"),
        (LEGACY_FINANCIAL_INPUT_POLICY, "legacy"),
    ):
        artifacts = generate_client_pack(
            source_root,
            tmp_path / folder,
            redact_names=True,
            redact_amounts=True,
            financial_input_policy=policy,
        )
        with (
            artifacts.output_dir / "evidence" / "source_records.csv"
        ).open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        assert rows == [
            {
                "customer_name": "[REDACTED]",
                "total_amount": "0-99",
                "note": "line one\nline two",
            }
        ]


def test_csv_redaction_writes_each_row_before_requesting_the_next(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("total_amount\n1\n2\n", encoding="utf-8")
    target = tmp_path / "output" / "redacted.csv"
    target.parent.mkdir()
    events: list[object] = []

    class StreamingReader:
        fieldnames = ["total_amount"]

        def __init__(self, _handle: object, **_kwargs: object) -> None:
            pass

        def __iter__(self) -> Any:
            yield {"total_amount": "1"}
            assert events == ["header", {"total_amount": "0-99"}]
            yield {"total_amount": "2"}

    class RecordingWriter:
        def __init__(self, _handle: object, **_kwargs: object) -> None:
            pass

        def writeheader(self) -> None:
            events.append("header")

        def writerow(self, row: dict[str, Any]) -> None:
            events.append(row)

    monkeypatch.setattr(
        client_pack_module,
        "_validate_redaction_csv",
        lambda _source: ("total_amount",),
    )
    monkeypatch.setattr(client_pack_module.csv, "DictReader", StreamingReader)
    monkeypatch.setattr(client_pack_module.csv, "DictWriter", RecordingWriter)

    client_pack_module._redact_csv_file(
        source,
        target,
        ClientPackOptions(
            redact_amounts=True,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        ),
    )

    assert events == [
        "header",
        {"total_amount": "0-99"},
        {"total_amount": "0-99"},
    ]
    assert target.exists()
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_csv_redaction_failure_keeps_existing_target_and_removes_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("total_amount\n1\n2\n", encoding="utf-8")
    target = tmp_path / "output" / "redacted.csv"
    target.parent.mkdir()
    target.write_text("existing-safe-copy", encoding="utf-8")

    class TwoRowReader:
        fieldnames = ["total_amount"]

        def __init__(self, _handle: object, **_kwargs: object) -> None:
            pass

        def __iter__(self) -> Any:
            yield {"total_amount": "1"}
            yield {"total_amount": "2"}

    class FailingWriter:
        def __init__(self, _handle: object, **_kwargs: object) -> None:
            self.rows = 0

        def writeheader(self) -> None:
            pass

        def writerow(self, _row: dict[str, Any]) -> None:
            self.rows += 1
            if self.rows == 2:
                raise csv.Error("simulated concurrent parse failure")

    monkeypatch.setattr(
        client_pack_module,
        "_validate_redaction_csv",
        lambda _source: ("total_amount",),
    )
    monkeypatch.setattr(client_pack_module.csv, "DictReader", TwoRowReader)
    monkeypatch.setattr(client_pack_module.csv, "DictWriter", FailingWriter)

    with pytest.raises(
        ValueError,
        match=r"^Client pack CSV redaction input is invalid$",
    ) as captured:
        client_pack_module._redact_csv_file(
            source,
            target,
            ClientPackOptions(
                redact_amounts=True,
                financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            ),
        )

    assert isinstance(captured.value.__cause__, FileIngressError)
    assert captured.value.__cause__.code == "csv_structure_invalid"
    assert target.read_text(encoding="utf-8") == "existing-safe-copy"
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))
