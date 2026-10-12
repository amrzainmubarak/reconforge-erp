from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.connectors.camt053 import (
    Camt053Error,
    parse_camt053_bytes,
    parse_camt053_file,
    project_camt053_to_payment_statement_pages,
)

runner = CliRunner()


def _fixture() -> bytes:
    return (Path(__file__).parent / "golden" / "camt053" / "statement.xml").read_bytes()


def test_camt053_parser_is_exact_deterministic_and_preserves_statement_lineage() -> None:
    statement = parse_camt053_bytes(_fixture())

    assert statement.schema_version == "camt.053.001-bounded-v1"
    assert statement.message_id == "MSG-CAMT-001"
    assert statement.statement_id == "STMT-CAMT-001"
    assert statement.account_id == "DE89370400440532013000"
    assert statement.opening_balance is not None
    assert statement.opening_balance.signed_amount == "1000"
    assert statement.closing_balance is not None
    assert statement.closing_balance.signed_amount == "1080"
    assert [line.line_id for line in statement.lines] == ["ENTRY-CREDIT-001", "ENTRY-DEBIT-001"]
    assert [line.signed_amount for line in statement.lines] == ["100", "-20"]
    assert statement.lines[1].remittance_information == "Service fee | January"
    assert statement.source_digest

    whitespace_variant = b"\n" + _fixture().replace(b"  ", b"    ")
    assert parse_camt053_bytes(whitespace_variant).source_digest == statement.source_digest


def test_camt053_file_parser_and_cli_emit_replayable_json(tmp_path: Path) -> None:
    source = tmp_path / "statement.xml"
    source.write_bytes(_fixture())
    parsed = parse_camt053_file(str(source))
    output = tmp_path / "parsed.json"
    result = runner.invoke(app, ["connectors", "parse-camt053", str(source), "--output", str(output)])

    assert result.exit_code == 0
    assert output.is_file()
    rendered = json.loads(output.read_text(encoding="utf-8"))
    assert rendered["source_digest"] == parsed.source_digest
    assert rendered["lines"][1]["signed_amount"] == "-20"
    schema = json.loads(Path("docs/schemas/camt053_statement.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(rendered)


def test_camt053_projection_preserves_signed_payment_statement_lineage_and_pages() -> None:
    statement = parse_camt053_bytes(_fixture())
    pages = project_camt053_to_payment_statement_pages(statement, page_size=1)

    assert len(pages) == 2
    assert pages[0].next_cursor == "1"
    assert pages[1].next_cursor is None
    assert [record.line_id for page in pages for record in page.records] == [
        "ENTRY-CREDIT-001",
        "ENTRY-DEBIT-001",
    ]
    assert [record.amount for page in pages for record in page.records] == ["100", "-20"]
    assert pages[1].records[0].reference.startswith("ENTRY-DEBIT-001 | BANK-REF-002")


def test_camt053_projection_rejects_unbounded_page_size() -> None:
    statement = parse_camt053_bytes(_fixture())
    with pytest.raises(Camt053Error, match="page_size_invalid"):
        project_camt053_to_payment_statement_pages(statement, page_size=0)


def test_camt053_is_packaged_as_a_closed_connector_boundary() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/connectors/camt053.py" in manifest
    assert "include tests/test_connector_camt053.py" in manifest
    assert "include tests/golden/camt053/statement.xml" in manifest
    assert "include docs/schemas/camt053_statement.schema.json" in manifest
    assert "include docs/adr/0338-bounded-camt053-statement-ingestion.md" in manifest
    assert Path("docs/connectors/camt053-bounded-readonly.md").is_file()


@pytest.mark.parametrize(
    "mutator, error",
    [
        (lambda body: body.replace(b"ENTRY-DEBIT-001", b"ENTRY-CREDIT-001"), "identity_duplicate"),
        (
            lambda body: body.replace(
                b"<NtryRef>ENTRY-DEBIT-001</NtryRef>", b""
            ).replace(b"<AcctSvcrRef>BANK-REF-002</AcctSvcrRef>", b""),
            "identity_missing",
        ),
        (lambda body: body.replace(b"<Amt Ccy=\"EUR\">20.00</Amt>", b"<Amt Ccy=\"EUR\">NaN</Amt>"), "amount_non_finite"),
        (lambda body: body.replace(b"<ValDt><Dt>2026-01-04</Dt>", b"<ValDt><Dt>2026-01-02</Dt>"), "value_date_before_booking"),
    ],
)
def test_camt053_rejects_invalid_financial_or_identity_inputs(mutator, error: str) -> None:
    with pytest.raises(Camt053Error, match=error):
        parse_camt053_bytes(mutator(_fixture()))


def test_camt053_rejects_scientific_notation_in_amounts() -> None:
    scientific = _fixture().replace(b'<Amt Ccy="EUR">20.00</Amt>', b'<Amt Ccy="EUR">2e1</Amt>')
    with pytest.raises(Camt053Error, match="amount_invalid"):
        parse_camt053_bytes(scientific)


@pytest.mark.parametrize("amount", (b"1,00.00", b"(20.00)"))
def test_camt053_rejects_locale_or_accounting_amount_text(amount: bytes) -> None:
    invalid = _fixture().replace(b"100.00", amount, 1)
    with pytest.raises(Camt053Error, match="amount_invalid"):
        parse_camt053_bytes(invalid)


def test_camt053_canonicalizes_equivalent_amount_text_before_digest() -> None:
    canonical = parse_camt053_bytes(_fixture())
    equivalent = _fixture().replace(b"100.00", b"100.0").replace(b"20.00", b"20.0")
    replay = parse_camt053_bytes(equivalent)
    assert replay.source_digest == canonical.source_digest
    assert [line.amount for line in replay.lines] == ["100", "20"]


def test_camt053_rejects_entity_expansion_and_multiple_statements() -> None:
    hostile = b'<!DOCTYPE foo [<!ENTITY xxe "secret">]><Document>&xxe;</Document>'
    with pytest.raises(Camt053Error, match="xml_invalid"):
        parse_camt053_bytes(hostile)

    multiple = _fixture().replace(b"    </Stmt>", b"    </Stmt><Stmt><Id>SECOND</Id></Stmt>")
    with pytest.raises(Camt053Error, match="requires_one_statement"):
        parse_camt053_bytes(multiple)


def test_camt053_rejects_oversized_payload() -> None:
    with pytest.raises(Camt053Error, match="payload_too_large"):
        parse_camt053_bytes(_fixture(), maximum_bytes=32)
