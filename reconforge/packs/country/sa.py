"""Saudi Arabia statutory pack: ZATCA VAT rules and Phase 1 & Phase 2 TLV/QR encoding."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
from typing import Final

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
