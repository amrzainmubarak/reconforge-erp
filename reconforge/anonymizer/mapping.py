"""Stable anonymization maps."""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

PREFIX_BY_FIELD = {
    "customer_code": "CUST-ANON",
    "customer_name": "Customer",
    "supplier_code": "SUP-ANON",
    "supplier_name": "Supplier",
    "created_by": "USER",
    "received_by": "USER",
    "responsible_engineer": "Engineer",
    "equipment_serial": "EQ-ANON",
    "invoice_number": "INV-ANON",
    "work_order": "WO-ANON",
    "linked_work_order": "WO-ANON",
    "source_document": "DOC-ANON",
    "reference": "DOC-ANON",
    "journal": "JRN-ANON",
    "po_number": "PO-ANON",
    "return_id": "RET-ANON",
}

GROUP_BY_FIELD = {
    "linked_work_order": "work_order",
    "work_order": "work_order",
    "source_document": "document",
    "reference": "document",
    "journal": "journal",
    "po_number": "document",
    "invoice_number": "invoice",
    "return_id": "return",
    "customer_code": "customer_code",
    "customer_name": "customer_name",
    "supplier_code": "supplier_code",
    "supplier_name": "supplier_name",
    "created_by": "user",
    "received_by": "user",
    "responsible_engineer": "engineer",
    "equipment_serial": "equipment",
}


@dataclass
class AnonymizationMap:
    """Deterministic mapping store preserving referential integrity."""

    seed: int = 42
    counters: dict[str, int] = field(default_factory=dict)
    values: dict[tuple[str, str], str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._random = Random(self.seed)

    def mask(self, field: str, value: object) -> str:
        text = str(value).strip()
        if text == "" or text.lower() in {"nan", "nat", "none"}:
            return ""
        group = GROUP_BY_FIELD.get(field, field)
        key = (group, text)
        if key in self.values:
            return self.values[key]
        self.counters[group] = self.counters.get(group, 0) + 1
        prefix = PREFIX_BY_FIELD.get(field, group.upper())
        if prefix in {"Customer", "Supplier", "Engineer"}:
            masked = f"{prefix} {self.counters[group]:04d}"
        else:
            masked = f"{prefix}-{self.counters[group]:04d}"
        self.values[key] = masked
        return masked

    def amount_factor(self, amount_noise_percent: float = 15.0) -> float:
        """Return a deterministic amount masking factor."""

        bounded = max(0.0, min(100.0, amount_noise_percent)) / 100
        return round(self._random.uniform(1 - bounded, 1 + bounded), 4)
