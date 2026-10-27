"""Independent XML ingress security contracts; no statutory compliance claim."""

from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.packs.country.sa import parse_zatca_ubl_xml

INVOICE = """<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
 <cbc:ID>{identifier}</cbc:ID><cbc:DocumentCurrencyCode>SAR</cbc:DocumentCurrencyCode>
 </Invoice>"""


@pytest.mark.parametrize(
    ("declaration", "identifier"),
    [
        ('<!DOCTYPE Invoice [<!ENTITY one "synthetic"><!ENTITY repeated "&one;&one;&one;&one;">]>', "&repeated;"),
        ('<!DOCTYPE Invoice [<!ENTITY value "forged-invoice-number">]>', "&value;"),
        ("<!DOCTYPE Invoice>", "INV-1"),
        ('<!DOCTYPE Invoice SYSTEM "https://synthetic.invalid/external.dtd">', "INV-1"),
        ('<!DOCTYPE Invoice [<!ENTITY % ignored "synthetic">]>', "INV-1"),
    ],
    ids=["bounded-entity-expansion", "internal-entity", "plain-dtd", "external-dtd", "parameter-entity"],
)
def test_invoice_parser_rejects_all_dtd_and_entity_declarations(declaration: str, identifier: str) -> None:
    # Expansion is intentionally tiny: prove the trust-boundary defect without
    # consuming substantial CPU/memory or contacting an external service.
    xml = declaration + INVOICE.format(identifier=identifier)
    with pytest.raises(ValueError, match="Unsafe XML declarations"):
        parse_zatca_ubl_xml(xml)


def test_invoice_external_file_entity_is_rejected_without_disclosing_local_content(tmp_path: Path) -> None:
    private_file = tmp_path / "synthetic-private.txt"
    private_file.write_text("SYNTHETIC-PRIVATE-SENTINEL", encoding="utf-8")
    xml = f'<!DOCTYPE Invoice [<!ENTITY external SYSTEM "{private_file.as_uri()}">]>' + INVOICE.format(identifier="&external;")

    with pytest.raises(ValueError, match="Unsafe XML declarations") as caught:
        parse_zatca_ubl_xml(xml)

    assert "SYNTHETIC-PRIVATE-SENTINEL" not in str(caught.value)
    assert str(private_file) not in str(caught.value)
    assert private_file.as_uri() not in str(caught.value)


def test_normal_invoice_preserves_unicode_and_literal_escaped_entities() -> None:
    result = parse_zatca_ubl_xml(INVOICE.format(identifier="فاتورة &amp; INV-1"))
    assert result["invoice_number"] == "فاتورة & INV-1"
    assert result["currency_code"] == "SAR"


def test_doctype_words_in_cdata_are_literal_text() -> None:
    result = parse_zatca_ubl_xml(INVOICE.format(identifier="<![CDATA[<!DOCTYPE is text>]]>"))
    assert result["invoice_number"] == "<!DOCTYPE is text>"
