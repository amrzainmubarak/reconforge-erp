from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "strategy" / "official-source-competitive-matrix-2026-08-05.md"


def test_official_competitive_matrix_is_source_linked_and_bounded() -> None:
    text = MATRIX.read_text(encoding="utf-8")
    required_sources = (
        "https://www.odoo.com/documentation/19.0/applications/finance/accounting/bank/reconciliation.html",
        "https://www.odoo.com/documentation/18.0/applications/finance/accounting/bank/bank_synchronization.html",
        "https://docs.frappe.io/erpnext/accounting/introduction",
        "https://docs.frappe.io/erpnext/bank",
        "https://fineract.apache.org/docs/current/",
    )
    for source in required_sources:
        assert source in text

    assert "not rank products" in text
    assert "E-388" in text
    assert "E-392" in text
    assert "P4-IAM-001" in text
    assert "live erp/bank interoperability" in text.casefold()

    prohibited_unqualified_language = (
        "best globally",
        "bank-grade",
        "enterprise-ready",
        "certified",
        "compliant",
    )
    lowered = text.casefold()
    assert all(term not in lowered for term in prohibited_unqualified_language)
