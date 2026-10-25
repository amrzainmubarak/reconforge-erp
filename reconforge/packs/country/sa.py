"""Saudi Arabia statutory pack: ZATCA VAT rules and Phase 1 & Phase 2 TLV/QR encoding."""

from __future__ import annotations

import base64
# The standard library tree is used for XML generation; parsing uses DefusedET.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from reconforge.packs.tax.models import TaxCategory, TaxRate

SA_VAT_STANDARD_CURRENT_BPS: Final[int] = 1500  # 15.00% effective 2020-07-01
SA_VAT_STANDARD_HISTORICAL_BPS: Final[int] = 500  # 5.00% (2018-01-01 to 2020-06-30)
SA_VAT_ZERO_RATED_BPS: Final[int] = 0

SA_ZATCA_PHASE1_EFFECTIVE: Final[str] = "2021-12-04"
SA_ZATCA_PHASE2_EFFECTIVE: Final[str] = "2023-01-01"


def get_sa_vat_rate_for_date(posting_date: str) -> TaxRate:
    """Return statutory Saudi VAT rate effective on the transaction date."""
    d = date.fromisoformat(posting_date)
    if d >= date(2020, 7, 1):
        return TaxRate(
            tax_id="SA-VAT-15",
            name="Saudi Arabia Standard VAT 15%",
            country_code="SA",
            category=TaxCategory.STANDARD,
            rate_basis_points=SA_VAT_STANDARD_CURRENT_BPS,
            account_code="2210_VAT_OUTPUT",
        )
    if d >= date(2018, 1, 1):
        return TaxRate(
            tax_id="SA-VAT-5",
            name="Saudi Arabia Historical Standard VAT 5%",
            country_code="SA",
            category=TaxCategory.STANDARD,
            rate_basis_points=SA_VAT_STANDARD_HISTORICAL_BPS,
            account_code="2210_VAT_OUTPUT",
        )
    raise ValueError(f"Transaction date {posting_date} precedes Saudi VAT introduction (2018-01-01).")


def encode_zatca_tlv_tag(tag_num: int, value: str | bytes) -> bytes:
    """Encode a single TLV tag according to ZATCA e-invoicing specification."""
    if not (1 <= tag_num <= 9):
        raise ValueError(f"ZATCA tag number must be between 1 and 9 (got {tag_num}).")
    val_bytes = value.encode("utf-8") if isinstance(value, str) else value
    length = len(val_bytes)
    if length > 255:
        raise ValueError(f"ZATCA TLV tag {tag_num} length exceeds 255 bytes (got {length}).")
    return bytes([tag_num, length]) + val_bytes


def generate_zatca_qr_tlv(
    seller_name: str,
    vat_number: str,
    timestamp_iso: str,
    invoice_total_gross_formatted: str,
    vat_total_formatted: str,
    *,
    xml_hash: bytes | None = None,
    ecdsa_signature: bytes | None = None,
    ecdsa_public_key: bytes | None = None,
    cryptographic_stamp: bytes | None = None,
) -> str:
    """Generate standard Base64-encoded TLV string for ZATCA Phase 1 & Phase 2 QR codes.

    Tags:
      1: Seller's Name (UTF-8)
      2: Seller's VAT Registration Number (15 digits)
      3: Time Stamp (ISO-8601 UTC)
      4: Invoice Total (with VAT)
      5: VAT Total
      6: SHA-256 Hash of invoice XML (Phase 2)
      7: ECDSA Digital Signature (Phase 2)
      8: ECDSA Public Key (Phase 2)
      9: Cryptographic Stamp Identifier (Phase 2)
    """
    if len(vat_number) != 15 or not vat_number.isdigit() or not (vat_number.startswith("3") and vat_number.endswith("3")):
        raise ValueError("Saudi VAT number must be exactly 15 digits starting and ending with 3.")

    tlv_buffer = bytearray()
    tlv_buffer.extend(encode_zatca_tlv_tag(1, seller_name.strip()))
    tlv_buffer.extend(encode_zatca_tlv_tag(2, vat_number.strip()))
    tlv_buffer.extend(encode_zatca_tlv_tag(3, timestamp_iso.strip()))
    tlv_buffer.extend(encode_zatca_tlv_tag(4, invoice_total_gross_formatted.strip()))
    tlv_buffer.extend(encode_zatca_tlv_tag(5, vat_total_formatted.strip()))

    if xml_hash is not None:
        tlv_buffer.extend(encode_zatca_tlv_tag(6, xml_hash))
    if ecdsa_signature is not None:
        tlv_buffer.extend(encode_zatca_tlv_tag(7, ecdsa_signature))
    if ecdsa_public_key is not None:
        tlv_buffer.extend(encode_zatca_tlv_tag(8, ecdsa_public_key))
    if cryptographic_stamp is not None:
        tlv_buffer.extend(encode_zatca_tlv_tag(9, cryptographic_stamp))

    return base64.b64encode(tlv_buffer).decode("ascii")


def parse_zatca_qr_tlv(base64_qr: str) -> dict[int, bytes]:
    """Parse a Base64 ZATCA QR code into individual Tag-Length-Value records."""
    raw = base64.b64decode(base64_qr.strip())
    tags: dict[int, bytes] = {}
    cursor = 0
    while cursor < len(raw):
        if cursor + 2 > len(raw):
            raise ValueError("Corrupt TLV byte stream: truncated header.")
        tag_num = raw[cursor]
        tag_len = raw[cursor + 1]
        cursor += 2
        if cursor + tag_len > len(raw):
            raise ValueError(f"Corrupt TLV byte stream: tag {tag_num} length {tag_len} exceeds remaining bytes.")
        tags[tag_num] = raw[cursor : cursor + tag_len]
        cursor += tag_len
    return tags


@dataclass(frozen=True)
class ZatcaInvoiceMetadata:
    """Canonical ZATCA UBL 2.1 e-invoice header metadata."""

    uuid: str
    invoice_number: str
    issue_date: str
    issue_time: str
    invoice_type_code: str  # e.g., "388" (Tax Invoice) or "381" (Credit Note) or "383" (Debit Note)
    sub_type: str  # "0100000" (Standard) or "0200000" (Simplified)
    seller_name: str
    seller_vat_number: str
    buyer_name: str
    buyer_vat_number: str | None
    currency_code: str = "SAR"


def format_zatca_minor_amount(minor: int) -> str:
    """Format integer minor units as decimal string without floating point arithmetic."""
    if not isinstance(minor, int):
        raise TypeError(f"Amount must be an integer (zero-float policy, got {type(minor)}).")
    sign = "-" if minor < 0 else ""
    abs_val = abs(minor)
    return f"{sign}{abs_val // 100}.{abs_val % 100:02d}"


@dataclass(frozen=True)
class ZatcaInvoiceLine:
    """Line item for ZATCA UBL 2.1 e-invoice."""

    line_id: str
    item_name: str
    quantity: int
    unit_price_minor: int
    net_amount_minor: int
    vat_rate_bps: int
    vat_amount_minor: int
    gross_amount_minor: int
    unit_code: str = "PCE"

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError(f"Quantity must be a positive integer (got {self.quantity}).")
        for attr in (
            "unit_price_minor",
            "net_amount_minor",
            "vat_rate_bps",
            "vat_amount_minor",
            "gross_amount_minor",
        ):
            val = getattr(self, attr)
            if not isinstance(val, int):
                raise TypeError(f"{attr} must be an integer (zero-float policy, got {type(val)}).")
        if self.net_amount_minor + self.vat_amount_minor != self.gross_amount_minor:
            raise ValueError(
                f"Line math invariant violated: net ({self.net_amount_minor}) + vat ({self.vat_amount_minor}) != gross ({self.gross_amount_minor})"
            )


UBL_NAMESPACES: Final[dict[str, str]] = {
    "xmlns": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


def build_zatca_ubl_xml(
    metadata: ZatcaInvoiceMetadata,
    lines: list[ZatcaInvoiceLine],
    *,
    qr_tlv_base64: str | None = None,
) -> str:
    """Generate standard ZATCA UBL 2.1 XML envelope embedding Base64 QR code and canonical invoice fields."""
    if not lines:
        raise ValueError("ZATCA invoice must contain at least one line item.")

    total_net_minor = sum(line.net_amount_minor for line in lines)
    total_vat_minor = sum(line.vat_amount_minor for line in lines)
    total_gross_minor = sum(line.gross_amount_minor for line in lines)

    if qr_tlv_base64 is None:
        timestamp = (
            f"{metadata.issue_date}T{metadata.issue_time}"
            if "T" in metadata.issue_time
            else f"{metadata.issue_date}T{metadata.issue_time}Z"
        )
        qr_tlv_base64 = generate_zatca_qr_tlv(
            seller_name=metadata.seller_name,
            vat_number=metadata.seller_vat_number,
            timestamp_iso=timestamp,
            invoice_total_gross_formatted=format_zatca_minor_amount(total_gross_minor),
            vat_total_formatted=format_zatca_minor_amount(total_vat_minor),
        )

    ET.register_namespace("", "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2")
    ET.register_namespace("cac", "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2")
    ET.register_namespace("cbc", "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2")

    ns_inv = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
    ns_cac = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
    ns_cbc = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

    def q_inv(tag: str) -> str:
        return f"{{{ns_inv}}}{tag}"

    def q_cac(tag: str) -> str:
        return f"{{{ns_cac}}}{tag}"

    def q_cbc(tag: str) -> str:
        return f"{{{ns_cbc}}}{tag}"

    root = ET.Element(q_inv("Invoice"))

    prof_elem = ET.SubElement(root, q_cbc("ProfileID"))
    prof_elem.text = "reporting:1.0"

    id_elem = ET.SubElement(root, q_cbc("ID"))
    id_elem.text = metadata.invoice_number

    uuid_elem = ET.SubElement(root, q_cbc("UUID"))
    uuid_elem.text = metadata.uuid

    date_elem = ET.SubElement(root, q_cbc("IssueDate"))
    date_elem.text = metadata.issue_date

    time_elem = ET.SubElement(root, q_cbc("IssueTime"))
    time_elem.text = metadata.issue_time

    type_code_elem = ET.SubElement(root, q_cbc("InvoiceTypeCode"), name=metadata.sub_type)
    type_code_elem.text = metadata.invoice_type_code

    doc_curr_elem = ET.SubElement(root, q_cbc("DocumentCurrencyCode"))
    doc_curr_elem.text = metadata.currency_code
    tax_curr_elem = ET.SubElement(root, q_cbc("TaxCurrencyCode"))
    tax_curr_elem.text = metadata.currency_code

    add_doc_elem = ET.SubElement(root, q_cac("AdditionalDocumentReference"))
    add_doc_id = ET.SubElement(add_doc_elem, q_cbc("ID"))
    add_doc_id.text = "QR"
    attach_elem = ET.SubElement(add_doc_elem, q_cac("Attachment"))
    embed_elem = ET.SubElement(attach_elem, q_cbc("EmbeddedDocumentBinaryObject"), mimeCode="text/plain")
    embed_elem.text = qr_tlv_base64

    supp_elem = ET.SubElement(root, q_cac("AccountingSupplierParty"))
    supp_party = ET.SubElement(supp_elem, q_cac("Party"))
    supp_name_elem = ET.SubElement(supp_party, q_cac("PartyName"))
    supp_name_text = ET.SubElement(supp_name_elem, q_cbc("Name"))
    supp_name_text.text = metadata.seller_name
    supp_tax_scheme = ET.SubElement(supp_party, q_cac("PartyTaxScheme"))
    supp_company_id = ET.SubElement(supp_tax_scheme, q_cbc("CompanyID"))
    supp_company_id.text = metadata.seller_vat_number
    supp_ts = ET.SubElement(supp_tax_scheme, q_cac("TaxScheme"))
    supp_ts_id = ET.SubElement(supp_ts, q_cbc("ID"))
    supp_ts_id.text = "VAT"

    cust_elem = ET.SubElement(root, q_cac("AccountingCustomerParty"))
    cust_party = ET.SubElement(cust_elem, q_cac("Party"))
    cust_name_elem = ET.SubElement(cust_party, q_cac("PartyName"))
    cust_name_text = ET.SubElement(cust_name_elem, q_cbc("Name"))
    cust_name_text.text = metadata.buyer_name
    if metadata.buyer_vat_number:
        cust_tax_scheme = ET.SubElement(cust_party, q_cac("PartyTaxScheme"))
        cust_company_id = ET.SubElement(cust_tax_scheme, q_cbc("CompanyID"))
        cust_company_id.text = metadata.buyer_vat_number
        cust_ts = ET.SubElement(cust_tax_scheme, q_cac("TaxScheme"))
        cust_ts_id = ET.SubElement(cust_ts, q_cbc("ID"))
        cust_ts_id.text = "VAT"

    tax_total_elem = ET.SubElement(root, q_cac("TaxTotal"))
    tax_amt_elem = ET.SubElement(tax_total_elem, q_cbc("TaxAmount"), currencyID=metadata.currency_code)
    tax_amt_elem.text = format_zatca_minor_amount(total_vat_minor)

    legal_total_elem = ET.SubElement(root, q_cac("LegalMonetaryTotal"))
    line_ext_elem = ET.SubElement(legal_total_elem, q_cbc("LineExtensionAmount"), currencyID=metadata.currency_code)
    line_ext_elem.text = format_zatca_minor_amount(total_net_minor)
    tax_excl_elem = ET.SubElement(legal_total_elem, q_cbc("TaxExclusiveAmount"), currencyID=metadata.currency_code)
    tax_excl_elem.text = format_zatca_minor_amount(total_net_minor)
    tax_incl_elem = ET.SubElement(legal_total_elem, q_cbc("TaxInclusiveAmount"), currencyID=metadata.currency_code)
    tax_incl_elem.text = format_zatca_minor_amount(total_gross_minor)
    payable_elem = ET.SubElement(legal_total_elem, q_cbc("PayableAmount"), currencyID=metadata.currency_code)
    payable_elem.text = format_zatca_minor_amount(total_gross_minor)

    for line in lines:
        line_elem = ET.SubElement(root, q_cac("InvoiceLine"))
        l_id = ET.SubElement(line_elem, q_cbc("ID"))
        l_id.text = line.line_id
        l_qty = ET.SubElement(line_elem, q_cbc("InvoicedQuantity"), unitCode=line.unit_code)
        l_qty.text = str(line.quantity)
        l_net = ET.SubElement(line_elem, q_cbc("LineExtensionAmount"), currencyID=metadata.currency_code)
        l_net.text = format_zatca_minor_amount(line.net_amount_minor)

        l_tax_total = ET.SubElement(line_elem, q_cac("TaxTotal"))
        l_tax_amt = ET.SubElement(l_tax_total, q_cbc("TaxAmount"), currencyID=metadata.currency_code)
        l_tax_amt.text = format_zatca_minor_amount(line.vat_amount_minor)
        l_round_amt = ET.SubElement(l_tax_total, q_cbc("RoundingAmount"), currencyID=metadata.currency_code)
        l_round_amt.text = format_zatca_minor_amount(line.gross_amount_minor)

        l_item = ET.SubElement(line_elem, q_cac("Item"))
        l_item_name = ET.SubElement(l_item, q_cbc("Name"))
        l_item_name.text = line.item_name
        l_class_tax = ET.SubElement(l_item, q_cac("ClassifiedTaxCategory"))
        l_cat_id = ET.SubElement(l_class_tax, q_cbc("ID"))
        l_cat_id.text = "S"
        l_pct = ET.SubElement(l_class_tax, q_cbc("Percent"))
        l_pct.text = format_zatca_minor_amount(line.vat_rate_bps)
        l_item_ts = ET.SubElement(l_class_tax, q_cac("TaxScheme"))
        l_item_ts_id = ET.SubElement(l_item_ts, q_cbc("ID"))
        l_item_ts_id.text = "VAT"

        l_price = ET.SubElement(line_elem, q_cac("Price"))
        l_price_amt = ET.SubElement(l_price, q_cbc("PriceAmount"), currencyID=metadata.currency_code)
        l_price_amt.text = format_zatca_minor_amount(line.unit_price_minor)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def parse_zatca_ubl_xml(xml_content: str) -> dict[str, Any]:
    """Parse a ZATCA UBL 2.1 XML document and extract canonical metadata, totals, and embedded QR code."""
    try:
        root = DefusedET.fromstring(xml_content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException:
        raise ValueError("Unsafe XML declarations are not permitted in invoice input.") from None
    ns = {
        "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }

    def find_text(elem: ET.Element | None, path: str) -> str:
        if elem is None:
            return ""
        node = elem.find(path, ns)
        return node.text.strip() if node is not None and node.text else ""

    invoice_number = find_text(root, "cbc:ID")
    uuid = find_text(root, "cbc:UUID")
    issue_date = find_text(root, "cbc:IssueDate")
    issue_time = find_text(root, "cbc:IssueTime")
    type_code_elem = root.find("cbc:InvoiceTypeCode", ns)
    invoice_type_code = type_code_elem.text.strip() if type_code_elem is not None and type_code_elem.text else ""
    sub_type = type_code_elem.attrib.get("name", "") if type_code_elem is not None else ""
    currency_code = find_text(root, "cbc:DocumentCurrencyCode")

    qr_code = find_text(root, "cac:AdditionalDocumentReference/cac:Attachment/cbc:EmbeddedDocumentBinaryObject")
    seller_name = find_text(root, "cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name")
    seller_vat = find_text(root, "cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID")
    buyer_name = find_text(root, "cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name")
    buyer_vat = find_text(root, "cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID")

    vat_total = find_text(root, "cac:TaxTotal/cbc:TaxAmount")
    net_total = find_text(root, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount")
    gross_total = find_text(root, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")

    lines_data: list[dict[str, str]] = []
    for line_node in root.findall("cac:InvoiceLine", ns):
        lines_data.append(
            {
                "line_id": find_text(line_node, "cbc:ID"),
                "quantity": find_text(line_node, "cbc:InvoicedQuantity"),
                "net_amount": find_text(line_node, "cbc:LineExtensionAmount"),
                "vat_amount": find_text(line_node, "cac:TaxTotal/cbc:TaxAmount"),
                "gross_amount": find_text(line_node, "cac:TaxTotal/cbc:RoundingAmount"),
                "item_name": find_text(line_node, "cac:Item/cbc:Name"),
                "vat_rate": find_text(line_node, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"),
                "unit_price": find_text(line_node, "cac:Price/cbc:PriceAmount"),
            }
        )

    return {
        "invoice_number": invoice_number,
        "uuid": uuid,
        "issue_date": issue_date,
        "issue_time": issue_time,
        "invoice_type_code": invoice_type_code,
        "sub_type": sub_type,
        "currency_code": currency_code,
        "seller_name": seller_name,
        "seller_vat_number": seller_vat,
        "buyer_name": buyer_name,
        "buyer_vat_number": buyer_vat or None,
        "qr_tlv_base64": qr_code,
        "net_total_formatted": net_total,
        "vat_total_formatted": vat_total,
        "gross_total_formatted": gross_total,
        "lines": lines_data,
    }
