"""Egypt statutory pack: Egyptian Tax Authority (ETA) e-invoicing and VAT rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from reconforge.packs.tax.models import TaxCategory, TaxRate

EG_VAT_STANDARD_BPS: Final[int] = 1400  # 14.00%
EG_VAT_MACHINERY_BPS: Final[int] = 500  # 5.00% for capital equipment
EG_VAT_ZERO_RATED_BPS: Final[int] = 0
EG_ETA_PHASE1_EFFECTIVE: Final[str] = "2020-11-15"


def validate_eg_tax_id(tax_id: str) -> bool:
    """Validate Egyptian 9-digit Tax Registration Number."""
    clean = tax_id.strip().replace("-", "")
    return len(clean) == 9 and clean.isdigit()


def get_eg_vat_rate(category: TaxCategory = TaxCategory.STANDARD) -> TaxRate:
    """Return statutory rate for Egyptian Tax Authority VAT."""
    if category == TaxCategory.STANDARD:
        return TaxRate(
            tax_id="EG-VAT-STD-14",
            name="Egypt Standard VAT 14%",
            country_code="EG",
            category=TaxCategory.STANDARD,
            rate_basis_points=EG_VAT_STANDARD_BPS,
            account_code="2200_VAT_OUTPUT_EG",
        )
    if category == TaxCategory.REDUCED:
        return TaxRate(
            tax_id="EG-VAT-MACH-5",
            name="Egypt Capital Machinery VAT 5%",
            country_code="EG",
            category=TaxCategory.REDUCED,
            rate_basis_points=EG_VAT_MACHINERY_BPS,
            account_code="2200_VAT_OUTPUT_EG",
        )
    if category in {TaxCategory.ZERO_RATED, TaxCategory.EXEMPT}:
        return TaxRate(
            tax_id=f"EG-VAT-{category.value.upper()}",
            name=f"Egypt VAT {category.value.capitalize()}",
            country_code="EG",
            category=category,
            rate_basis_points=EG_VAT_ZERO_RATED_BPS,
            account_code="2200_VAT_OUTPUT_EG",
        )
    raise ValueError(f"Unsupported Egyptian tax category: {category}")


@dataclass(frozen=True)
class ETADocumentHeader:
    """Egyptian Tax Authority (ETA) e-invoicing standard document header."""

    issuer_id: str
    issuer_name: str
    receiver_id: str
    receiver_name: str
    document_type: str  # "I" for Invoice, "C" for Credit Note, "D" for Debit Note
    document_type_version: str  # e.g., "1.0" or "0.9"
    date_time_issued: str
    taxpayer_activity_code: str
    internal_id: str

    def __post_init__(self) -> None:
        if not validate_eg_tax_id(self.issuer_id):
            raise ValueError(f"Invalid Egyptian issuer tax ID: {self.issuer_id}")
        if self.document_type not in {"I", "C", "D"}:
            raise ValueError(f"ETA document_type must be 'I', 'C', or 'D' (got '{self.document_type}').")


def format_egp_minor(minor: int) -> str:
    """Format Egyptian Pound minor units as 2-decimal string without float arithmetic."""
    if not isinstance(minor, int):
        raise TypeError(f"Amount must be an integer (zero-float policy, got {type(minor)}).")
    sign = "-" if minor < 0 else ""
    abs_val = abs(minor)
    return f"{sign}{abs_val // 100}.{abs_val % 100:02d}"


@dataclass(frozen=True)
class ETALineItem:
    """Line item for Egyptian Tax Authority (ETA) e-invoice."""

    description: str
    item_type: str  # "GS1" or "EGS"
    item_code: str
    unit_type: str  # e.g., "EA", "KGM", "PCE"
    quantity: int
    unit_price_minor: int
    sales_total_minor: int
    net_total_minor: int
    tax_rate_bps: int
    tax_amount_minor: int
    total_amount_minor: int
    discount_minor: int = 0
    tax_type: str = "T1"  # T1 = VAT
    sub_type: str = "V009"  # V009 = General Tax

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError(f"Quantity must be a positive integer (got {self.quantity}).")
        if self.item_type not in {"GS1", "EGS"}:
            raise ValueError(f"ETA item_type must be 'GS1' or 'EGS' (got '{self.item_type}').")
        for attr in (
            "unit_price_minor",
            "sales_total_minor",
            "net_total_minor",
            "tax_rate_bps",
            "tax_amount_minor",
            "total_amount_minor",
            "discount_minor",
        ):
            val = getattr(self, attr)
            if not isinstance(val, int):
                raise TypeError(f"{attr} must be an integer (zero-float policy, got {type(val)}).")
        if self.sales_total_minor - self.discount_minor != self.net_total_minor:
            raise ValueError(
                f"ETA line math invariant violated: sales ({self.sales_total_minor}) - discount ({self.discount_minor}) != net ({self.net_total_minor})"
            )
        if self.net_total_minor + self.tax_amount_minor != self.total_amount_minor:
            raise ValueError(
                f"ETA line math invariant violated: net ({self.net_total_minor}) + tax ({self.tax_amount_minor}) != total ({self.total_amount_minor})"
            )


def build_eta_invoice_json(
    header: ETADocumentHeader,
    lines: list[ETALineItem],
    *,
    issuer_type: str = "B",
    issuer_address: dict[str, str] | None = None,
    receiver_type: str = "B",
    receiver_address: dict[str, str] | None = None,
    extra_discount_minor: int = 0,
) -> dict[str, Any]:
    """Generate standard Egyptian Tax Authority (ETA) e-invoice JSON structure."""
    if not lines:
        raise ValueError("ETA invoice must contain at least one line item.")
    if not isinstance(extra_discount_minor, int):
        raise TypeError(f"extra_discount_minor must be an integer (got {type(extra_discount_minor)}).")

    default_issuer_address = {
        "branchID": "0",
        "country": "EG",
        "governate": "Cairo",
        "regionCity": "Nasr City",
        "street": "Main Road",
        "buildingNumber": "1",
    }
    default_receiver_address = {
        "country": "EG",
        "governate": "Cairo",
        "regionCity": "Nasr City",
        "street": "Customer Road",
        "buildingNumber": "1",
    }

    final_issuer_addr = issuer_address or default_issuer_address
    final_receiver_addr = receiver_address or default_receiver_address

    total_sales_minor = sum(line.sales_total_minor for line in lines)
    total_items_discount_minor = sum(line.discount_minor for line in lines)
    net_amount_minor = sum(line.net_total_minor for line in lines)
    total_tax_minor = sum(line.tax_amount_minor for line in lines)
    grand_total_minor = net_amount_minor + total_tax_minor - extra_discount_minor

    formatted_lines: list[dict[str, Any]] = []
    for line in lines:
        formatted_lines.append(
            {
                "description": line.description,
                "itemType": line.item_type,
                "itemCode": line.item_code,
                "unitType": line.unit_type,
                "quantity": line.quantity,
                "unitValue": {
                    "currencySold": "EGP",
                    "amountEGP": format_egp_minor(line.unit_price_minor),
                    "amountSold": format_egp_minor(line.unit_price_minor),
                    "currencyExchangeRate": 1,
                },
                "salesTotal": format_egp_minor(line.sales_total_minor),
                "total": format_egp_minor(line.total_amount_minor),
                "valueDifference": "0.00",
                "totalTaxableFees": "0.00",
                "netTotal": format_egp_minor(line.net_total_minor),
                "itemsDiscount": format_egp_minor(line.discount_minor),
                "taxableItems": [
                    {
                        "taxType": line.tax_type,
                        "amount": format_egp_minor(line.tax_amount_minor),
                        "subType": line.sub_type,
                        "rate": format_egp_minor(line.tax_rate_bps),
                    }
                ],
            }
        )

    return {
        "issuer": {
            "address": final_issuer_addr,
            "type": issuer_type,
            "id": header.issuer_id,
            "name": header.issuer_name,
        },
        "receiver": {
            "address": final_receiver_addr,
            "type": receiver_type,
            "id": header.receiver_id,
            "name": header.receiver_name,
        },
        "documentType": header.document_type,
        "documentTypeVersion": header.document_type_version,
        "dateTimeIssued": header.date_time_issued,
        "taxpayerActivityCode": header.taxpayer_activity_code,
        "internalId": header.internal_id,
        "invoiceLines": formatted_lines,
        "totalSalesAmount": format_egp_minor(total_sales_minor),
        "totalDiscountAmount": format_egp_minor(total_items_discount_minor),
        "netAmount": format_egp_minor(net_amount_minor),
        "taxTotals": [
            {
                "taxType": "T1",
                "amount": format_egp_minor(total_tax_minor),
            }
        ],
        "extraDiscountAmount": format_egp_minor(extra_discount_minor),
        "totalAmount": format_egp_minor(grand_total_minor),
    }


def validate_eta_invoice_payload(payload: dict[str, Any]) -> bool:
    """Validate ETA invoice JSON payload against statutory constraints."""
    required_root_keys = {
        "issuer",
        "receiver",
        "documentType",
        "documentTypeVersion",
        "dateTimeIssued",
        "taxpayerActivityCode",
        "internalId",
        "invoiceLines",
        "totalSalesAmount",
        "totalDiscountAmount",
        "netAmount",
        "taxTotals",
        "extraDiscountAmount",
        "totalAmount",
    }
    if not required_root_keys.issubset(payload.keys()):
        missing = required_root_keys - payload.keys()
        raise ValueError(f"Missing required ETA root fields: {missing}")

    issuer = payload["issuer"]
    if not isinstance(issuer, dict) or not validate_eg_tax_id(str(issuer.get("id", ""))):
        raise ValueError("Invalid issuer block or tax ID in ETA payload.")

    receiver = payload["receiver"]
    if not isinstance(receiver, dict) or not receiver.get("id"):
        raise ValueError("Invalid receiver block in ETA payload.")

    if payload["documentType"] not in {"I", "C", "D"}:
        raise ValueError(f"Invalid ETA documentType: {payload['documentType']}")

    lines = payload.get("invoiceLines", [])
    if not isinstance(lines, list) or len(lines) == 0:
        raise ValueError("ETA payload must contain a non-empty invoiceLines list.")

    # Audit for float values anywhere in payload
    def _check_no_floats(obj: Any) -> None:
        if isinstance(obj, float):
            raise TypeError("Floating-point value detected in ETA payload (zero-float violation).")
        if isinstance(obj, dict):
            for v in obj.values():
                _check_no_floats(v)
        elif isinstance(obj, list):
            for item in obj:
                _check_no_floats(item)

    _check_no_floats(payload)
    return True
