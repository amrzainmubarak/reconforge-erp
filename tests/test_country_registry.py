"""Tests for Country Coverage Registry and jurisdiction qualification contracts."""

import pytest

from reconforge.packs.country_registry import (
    GLOBAL_COUNTRY_REGISTRY,
    CountryCoverageRegistry,
    StatutoryPackDeclaration,
    UnsupportedCountryJurisdictionError,
)


def test_statutory_pack_validation_rules() -> None:
    # Invalid country code
    with pytest.raises(ValueError, match="2-letter uppercase ISO"):
        StatutoryPackDeclaration(
            country_code="USA",
            jurisdiction_name="United States",
            pack_category="tax_vat",
            version="1.0.0",
            effective_from="2024-01-01",
            effective_to=None,
            status="planned",
            external_review_ref=None,
            capabilities=(),
        )

    # Inverted date window
    with pytest.raises(ValueError, match="cannot succeed effective_to"):
        StatutoryPackDeclaration(
            country_code="US",
            jurisdiction_name="United States",
            pack_category="tax_vat",
            version="1.0.0",
            effective_from="2025-01-01",
            effective_to="2024-12-31",
            status="planned",
            external_review_ref=None,
            capabilities=(),
        )

    # Verified without external review
    with pytest.raises(ValueError, match="require an explicit external review reference"):
        StatutoryPackDeclaration(
            country_code="US",
            jurisdiction_name="United States",
            pack_category="tax_vat",
            version="1.0.0",
            effective_from="2024-01-01",
            effective_to=None,
            status="verified",
            external_review_ref=None,
            capabilities=("nexus",),
        )


def test_country_registry_unverified_pack_refusal() -> None:
    registry = CountryCoverageRegistry()
    pack = StatutoryPackDeclaration(
        country_code="SA",
        jurisdiction_name="Saudi Arabia",
        pack_category="tax_vat",
        version="1.0.0",
        effective_from="2020-07-01",
        effective_to=None,
        status="beta",
        external_review_ref=None,
        capabilities=("standard_15pct",),
    )
    registry.register(pack)

    # Querying unverified pack must refuse when requiring verified capability
    with pytest.raises(UnsupportedCountryJurisdictionError, match="has status 'beta'"):
        registry.require_verified_capability("SA", "tax_vat", "2024-01-01")

    # Unregistered jurisdiction refusal
    with pytest.raises(UnsupportedCountryJurisdictionError, match="is not registered"):
        registry.require_verified_capability("FR", "tax_vat", "2024-01-01")


def test_verified_pack_date_window_enforcement() -> None:
    registry = CountryCoverageRegistry()
    pack = StatutoryPackDeclaration(
        country_code="DE",
        jurisdiction_name="Germany (USt)",
        pack_category="tax_vat",
        version="2.1.0",
        effective_from="2021-01-01",
        effective_to="2025-12-31",
        status="verified",
        external_review_ref="DE-TAX-AUDIT-2021-CERT-009",
        capabilities=("standard_19pct", "reduced_7pct"),
    )
    registry.register(pack)

    # Valid in-window query
    verified = registry.require_verified_capability("DE", "tax_vat", "2023-06-15")
    assert verified.country_code == "DE"
    assert "standard_19pct" in verified.capabilities

    # Date preceding effective window
    with pytest.raises(UnsupportedCountryJurisdictionError, match="precedes pack effective date"):
        registry.require_verified_capability("DE", "tax_vat", "2020-12-31")

    # Date succeeding expiration
    with pytest.raises(UnsupportedCountryJurisdictionError, match="exceeds pack expiration date"):
        registry.require_verified_capability("DE", "tax_vat", "2026-01-01")


def test_global_registry_inventory_integrity() -> None:
    coverage = GLOBAL_COUNTRY_REGISTRY.list_coverage()
    assert len(coverage) >= 5
    country_codes = {entry["country_code"] for entry in coverage}
    assert {"SA", "AE", "US", "GB", "EG"}.issubset(country_codes)

    # SA e-invoicing is verified and valid in date window
    sa_einv = GLOBAL_COUNTRY_REGISTRY.require_verified_capability("SA", "einvoicing", "2024-01-01")
    assert sa_einv.country_code == "SA"
    assert "qr_tlv_encoding" in sa_einv.capabilities
    assert sa_einv.external_review_ref == "ZATCA-EINV-AUDIT-2021-V1"

    # AE VAT is verified
    ae_vat = GLOBAL_COUNTRY_REGISTRY.require_verified_capability("AE", "tax_vat", "2024-01-01")
    assert ae_vat.country_code == "AE"
    assert "designated_zones" in ae_vat.capabilities

    # GB MTD is verified
    gb_vat = GLOBAL_COUNTRY_REGISTRY.require_verified_capability("GB", "tax_vat", "2024-01-01")
    assert gb_vat.country_code == "GB"
    assert "mtd_vat_return" in gb_vat.capabilities


def test_zatca_phase1_and_phase2_tlv_qr_encoding() -> None:
    from reconforge.packs.country.sa import (
        generate_zatca_qr_tlv,
        get_sa_vat_rate_for_date,
        parse_zatca_qr_tlv,
    )

    # Date-effective VAT rates
    rate_2019 = get_sa_vat_rate_for_date("2019-06-15")
    assert rate_2019.rate_basis_points == 500
    rate_2024 = get_sa_vat_rate_for_date("2024-06-15")
    assert rate_2024.rate_basis_points == 1500

    # Phase 1 QR generation (Tags 1 to 5)
    qr_b64 = generate_zatca_qr_tlv(
        seller_name="ReconForge Enterprise Ltd",
        vat_number="300000000000003",
        timestamp_iso="2026-10-19T07:00:00Z",
        invoice_total_gross_formatted="115.00",
        vat_total_formatted="15.00",
    )
    assert isinstance(qr_b64, str)
    assert len(qr_b64) > 0

    parsed = parse_zatca_qr_tlv(qr_b64)
    assert parsed[1].decode("utf-8") == "ReconForge Enterprise Ltd"
    assert parsed[2].decode("utf-8") == "300000000000003"
    assert parsed[3].decode("utf-8") == "2026-10-19T07:00:00Z"
    assert parsed[4].decode("utf-8") == "115.00"
    assert parsed[5].decode("utf-8") == "15.00"

    # Phase 2 QR generation (Tags 1 to 9)
    xml_hash = b"\xaa" * 32
    signature = b"\xbb" * 64
    public_key = b"\xcc" * 64
    stamp = b"\xdd" * 16

    qr_p2 = generate_zatca_qr_tlv(
        seller_name="ReconForge Enterprise Ltd",
        vat_number="300000000000003",
        timestamp_iso="2026-10-19T07:00:00Z",
        invoice_total_gross_formatted="115.00",
        vat_total_formatted="15.00",
        xml_hash=xml_hash,
        ecdsa_signature=signature,
        ecdsa_public_key=public_key,
        cryptographic_stamp=stamp,
    )
    parsed_p2 = parse_zatca_qr_tlv(qr_p2)
    assert parsed_p2[6] == xml_hash
    assert parsed_p2[7] == signature
    assert parsed_p2[8] == public_key
    assert parsed_p2[9] == stamp


def test_zatca_ubl_xml_envelope_builder() -> None:
    from reconforge.packs.country.sa import (
        ZatcaInvoiceLine,
        ZatcaInvoiceMetadata,
        build_zatca_ubl_xml,
        parse_zatca_qr_tlv,
        parse_zatca_ubl_xml,
    )

    metadata = ZatcaInvoiceMetadata(
        uuid="c3053641-a123-4b67-8910-bcde12345678",
        invoice_number="INV-2026-0001",
        issue_date="2026-10-19",
        issue_time="08:30:00",
        invoice_type_code="388",
        sub_type="0100000",
        seller_name="ReconForge Enterprise Ltd",
        seller_vat_number="300000000000003",
        buyer_name="Client Trading Co",
        buyer_vat_number="300000000000013",
        currency_code="SAR",
    )

    lines = [
        ZatcaInvoiceLine(
            line_id="1",
            item_name="Consulting Services",
            quantity=1,
            unit_price_minor=10000,
            net_amount_minor=10000,
            vat_rate_bps=1500,
            vat_amount_minor=1500,
            gross_amount_minor=11500,
        ),
        ZatcaInvoiceLine(
            line_id="2",
            item_name="Software License",
            quantity=2,
            unit_price_minor=5000,
            net_amount_minor=10000,
            vat_rate_bps=1500,
            vat_amount_minor=1500,
            gross_amount_minor=11500,
        ),
    ]

    xml_str = build_zatca_ubl_xml(metadata, lines)
    assert "<?xml" in xml_str
    assert "<Invoice" in xml_str
    assert "c3053641-a123-4b67-8910-bcde12345678" in xml_str
    assert "INV-2026-0001" in xml_str

    parsed = parse_zatca_ubl_xml(xml_str)
    assert parsed["uuid"] == "c3053641-a123-4b67-8910-bcde12345678"
    assert parsed["invoice_number"] == "INV-2026-0001"
    assert parsed["seller_vat_number"] == "300000000000003"
    assert parsed["buyer_vat_number"] == "300000000000013"
    assert parsed["net_total_formatted"] == "200.00"
    assert parsed["vat_total_formatted"] == "30.00"
    assert parsed["gross_total_formatted"] == "230.00"
    assert len(parsed["lines"]) == 2

    qr_b64 = parsed["qr_tlv_base64"]
    qr_tags = parse_zatca_qr_tlv(qr_b64)
    assert qr_tags[1].decode("utf-8") == "ReconForge Enterprise Ltd"
    assert qr_tags[2].decode("utf-8") == "300000000000003"
    assert qr_tags[4].decode("utf-8") == "230.00"
    assert qr_tags[5].decode("utf-8") == "30.00"

    with pytest.raises(ValueError, match="Line math invariant violated"):
        ZatcaInvoiceLine(
            line_id="err",
            item_name="Bad line",
            quantity=1,
            unit_price_minor=1000,
            net_amount_minor=1000,
            vat_rate_bps=1500,
            vat_amount_minor=150,
            gross_amount_minor=1200,
        )


def test_uae_fta_vat_and_designated_zones() -> None:
    from reconforge.packs.country.ae import (
        AETaxInvoiceSummary,
        get_ae_vat_rate,
        is_designated_zone_supply,
        validate_ae_trn,
    )
    from reconforge.packs.tax.models import TaxCategory

    assert validate_ae_trn("100123456789012")
    assert not validate_ae_trn("200123456789012")  # Doesn't start with 100
    assert not validate_ae_trn("100123")  # Too short

    rate = get_ae_vat_rate(TaxCategory.STANDARD)
    assert rate.rate_basis_points == 500

    # Designated zone check
    assert is_designated_zone_supply("JAFZA", "DAFZA")
    assert not is_designated_zone_supply("JAFZA", "MAINLAND_DUBAI")

    # Invoice summary check
    summary = AETaxInvoiceSummary(
        trn_supplier="100123456789012",
        trn_customer=None,
        supply_date="2026-10-10",
        gross_minor=10500,
        net_minor=10000,
        vat_minor=500,
    )
    assert summary.gross_minor == summary.net_minor + summary.vat_minor


def test_uk_hmrc_mtd_vat_and_9box_return() -> None:
    from reconforge.packs.country.gb import HMRC9BoxVATReturn, get_gb_vat_rate
    from reconforge.packs.tax.models import TaxCategory

    std_rate = get_gb_vat_rate(TaxCategory.STANDARD)
    assert std_rate.rate_basis_points == 2000
    red_rate = get_gb_vat_rate(TaxCategory.REDUCED)
    assert red_rate.rate_basis_points == 500

    # 9-box return arithmetic
    vat_return = HMRC9BoxVATReturn(
        box1_vat_due_sales_minor=200000,
        box2_vat_due_acquisitions_minor=10000,
        box4_vat_reclaimed_minor=85000,
        box6_total_sales_ex_vat_minor=1000000,
        box7_total_purchases_ex_vat_minor=425000,
        box8_total_supplies_ex_vat_minor=50000,
        box9_total_acquisitions_ex_vat_minor=50000,
    )
    # Box 3 = Box 1 + Box 2 = 200,000 + 10,000 = 210,000
    assert vat_return.box3_total_vat_due_minor == 210000
    # Box 5 = Box 3 - Box 4 = 210,000 - 85,000 = 125,000 (payable)
    assert vat_return.box5_net_vat_due_minor == 125000


def test_egypt_eta_einvoicing_and_vat() -> None:
    from reconforge.packs.country.eg import ETADocumentHeader, get_eg_vat_rate, validate_eg_tax_id
    from reconforge.packs.tax.models import TaxCategory

    assert validate_eg_tax_id("123456789")
    assert not validate_eg_tax_id("12345")

    rate = get_eg_vat_rate(TaxCategory.STANDARD)
    assert rate.rate_basis_points == 1400

    header = ETADocumentHeader(
        issuer_id="123456789",
        issuer_name="Cairo Industrial Corp",
        receiver_id="987654321",
        receiver_name="Alexandria Trading Co",
        document_type="I",
        document_type_version="1.0",
        date_time_issued="2026-10-19T08:00:00Z",
        taxpayer_activity_code="4610",
        internal_id="INV-2026-001",
    )
    assert header.document_type == "I"


def test_eta_json_document_builder() -> None:
    from reconforge.packs.country.eg import (
        ETADocumentHeader,
        ETALineItem,
        build_eta_invoice_json,
        validate_eta_invoice_payload,
    )

    header = ETADocumentHeader(
        issuer_id="123456789",
        issuer_name="Cairo Industrial Corp",
        receiver_id="987654321",
        receiver_name="Alexandria Trading Co",
        document_type="I",
        document_type_version="1.0",
        date_time_issued="2026-10-19T08:00:00Z",
        taxpayer_activity_code="4610",
        internal_id="INV-2026-001",
    )

    lines = [
        ETALineItem(
            description="Industrial Valve V-100",
            item_type="EGS",
            item_code="EG-123456789-001",
            unit_type="EA",
            quantity=5,
            unit_price_minor=20000,
            sales_total_minor=100000,
            net_total_minor=100000,
            tax_rate_bps=1400,
            tax_amount_minor=14000,
            total_amount_minor=114000,
        ),
        ETALineItem(
            description="Seal Ring Set",
            item_type="GS1",
            item_code="6221234567890",
            unit_type="PCE",
            quantity=10,
            unit_price_minor=5000,
            sales_total_minor=50000,
            net_total_minor=45000,
            discount_minor=5000,
            tax_rate_bps=1400,
            tax_amount_minor=6300,
            total_amount_minor=51300,
        ),
    ]

    payload = build_eta_invoice_json(header, lines)
    assert validate_eta_invoice_payload(payload) is True

    # Assertions on payload structure and amounts
    assert payload["totalSalesAmount"] == "1500.00"
    assert payload["totalDiscountAmount"] == "50.00"
    assert payload["netAmount"] == "1450.00"
    assert payload["taxTotals"][0]["amount"] == "203.00"
    assert payload["totalAmount"] == "1653.00"
    assert len(payload["invoiceLines"]) == 2

    # Line item invariants
    with pytest.raises(ValueError, match=r"ETA line math invariant violated.*sales"):
        ETALineItem(
            description="Bad item",
            item_type="EGS",
            item_code="CODE",
            unit_type="EA",
            quantity=1,
            unit_price_minor=1000,
            sales_total_minor=1000,
            discount_minor=200,
            net_total_minor=900,  # 1000 - 200 != 900
            tax_rate_bps=1400,
            tax_amount_minor=126,
            total_amount_minor=1026,
        )

    # Float prohibition in payload validation
    bad_payload = dict(payload)
    bad_payload["totalAmount"] = 1653.0
    with pytest.raises(TypeError, match="Floating-point value detected"):
        validate_eta_invoice_payload(bad_payload)


def test_us_sales_tax_and_economic_nexus() -> None:
    from reconforge.packs.country.us import (
        determine_applicable_rate_bps,
        evaluate_economic_nexus,
    )

    # Remote seller with $150,000 sales -> has nexus
    assert evaluate_economic_nexus("CA", annual_sales_minor=15_000_000, annual_transactions=50)
    # Remote seller with 250 transactions -> has nexus
    assert evaluate_economic_nexus("CA", annual_sales_minor=5_000_000, annual_transactions=250)
    # Under both thresholds -> no nexus
    assert not evaluate_economic_nexus("CA", annual_sales_minor=5_000_000, annual_transactions=50)

    # Origin state vs destination state
    ca_rate = determine_applicable_rate_bps("CA", "TX", has_nexus_in_destination=False)
    assert ca_rate == 725  # Origin CA applies when no nexus in destination


def test_tax_engine_exact_integer_exclusive_and_inclusive_calculations() -> None:
    from reconforge.packs.tax.engine import (
        calculate_multi_rate_tax,
        calculate_tax_exclusive,
        calculate_tax_inclusive,
    )
    from reconforge.packs.tax.models import TaxCategory, TaxRate

    # 1. Tax Exclusive (15% VAT on 100.00 SAR = 10000 minor)
    res_ex = calculate_tax_exclusive(10000, 1500, currency="SAR")
    assert res_ex.net_total_minor == 10000
    assert res_ex.tax_total_minor == 1500
    assert res_ex.gross_total_minor == 11500
    assert res_ex.net_total_minor + res_ex.tax_total_minor == res_ex.gross_total_minor

    # 2. Half-up rounding boundary in exclusive:
    # Net = 333 minor (3.33 SAR), Rate = 15% (1500 bps).
    # Exact tax = 333 * 0.15 = 49.95 -> rounds up to 50 minor.
    res_halfup = calculate_tax_exclusive(333, 1500, currency="SAR")
    assert res_halfup.tax_total_minor == 50
    assert res_halfup.gross_total_minor == 383
    assert res_halfup.net_total_minor + res_halfup.tax_total_minor == res_halfup.gross_total_minor

    # 3. Tax Inclusive extraction (115.00 SAR gross with 15% VAT):
    # Net = 100.00 SAR (10000 minor), Tax = 15.00 SAR (1500 minor)
    res_inc = calculate_tax_inclusive(11500, 1500, currency="SAR")
    assert res_inc.net_total_minor == 10000
    assert res_inc.tax_total_minor == 1500
    assert res_inc.gross_total_minor == 11500
    assert res_inc.net_total_minor + res_inc.tax_total_minor == res_inc.gross_total_minor

    # 4. Tax Inclusive extraction on odd numbers with ZERO integer leakage:
    # Gross = 1000 minor, Rate = 15% (1500 bps).
    # Net = (1000 * 10000 + 5750) // 11500 = 10005750 // 11500 = 870 minor.
    # Tax = 1000 - 870 = 130 minor.
    # Check: 870 + 130 == 1000!
    res_inc_odd = calculate_tax_inclusive(1000, 1500, currency="SAR")
    assert res_inc_odd.net_total_minor == 870
    assert res_inc_odd.tax_total_minor == 130
    assert res_inc_odd.gross_total_minor == 1000
    assert res_inc_odd.net_total_minor + res_inc_odd.tax_total_minor == res_inc_odd.gross_total_minor

    # 5. Multi-rate calculation
    rate_15 = TaxRate(tax_id="VAT15", name="15%", country_code="SA", category=TaxCategory.STANDARD, rate_basis_points=1500)
    rate_0 = TaxRate(tax_id="VAT0", name="0%", country_code="SA", category=TaxCategory.ZERO_RATED, rate_basis_points=0)
    multi_res = calculate_multi_rate_tax([(10000, rate_15), (5000, rate_0)], currency="SAR", inclusive=False)
    assert multi_res.net_total_minor == 15000
    assert multi_res.tax_total_minor == 1500
    assert multi_res.gross_total_minor == 16500

    # 6. Float prohibition check
    with pytest.raises(TypeError):
        calculate_tax_exclusive(100.50, 1500)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        calculate_tax_inclusive(115.00, 1500)  # type: ignore[arg-type]
