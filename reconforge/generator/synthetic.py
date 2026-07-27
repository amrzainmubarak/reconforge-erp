"""Synthetic ERP dataset generator."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from random import Random
from typing import TypeVar

import pandas as pd

from reconforge.generator.scenarios import pick_profile, pick_scenario
from reconforge.io.writers import canonical_decimal_text
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    CurrencyRegistry,
    FinancialInputPolicy,
    InvalidAmountError,
    ResolvedCurrencyPolicy,
    parse_amount,
    validate_financial_input_policy,
)

T = TypeVar("T")
RateInput = Decimal | str | int
LegacyRateInput = RateInput | float
SYNTHETIC_GENERATOR_SCHEMA_VERSION = 2
SYNTHETIC_GENERATOR_ALGORITHM_VERSION = "exact-decimal-v1"
SYNTHETIC_RANDOM_SCALE = 6
_MAX_RATE_CHARS = 100
_EXPECTED_OUTPUT_FILES = {
    "customers.csv",
    "gl_entries.csv",
    "invoices.csv",
    "old_parts_returns.csv",
    "products.csv",
    "purchase_orders.csv",
    "stock_moves.csv",
    "work_orders.csv",
}


def parse_generation_rate(
    value: LegacyRateInput,
    *,
    field_name: str,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> Decimal:
    """Parse an exact synthetic frequency in the closed interval zero to one."""

    if isinstance(value, str) and len(value) > _MAX_RATE_CHARS:
        raise ValueError(f"{field_name} must be a bounded decimal between 0 and 1")
    try:
        parsed = parse_amount(value, input_policy=financial_input_policy)
    except (InvalidAmountError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a plain decimal between 0 and 1") from exc
    if parsed < 0 or parsed > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return parsed


def _money(value: object, policy: ResolvedCurrencyPolicy) -> Decimal:
    parsed = parse_amount(value, input_policy=STRICT_FINANCIAL_INPUT_POLICY)
    spec = policy.spec
    if spec.rounding_policy != "ROUND_HALF_UP":
        raise ValueError("Synthetic generator currency rounding policy is unsupported.")
    quantum = Decimal("1").scaleb(-spec.minor_units)
    integer_digits = max(1, parsed.adjusted() + 1) if parsed else 1
    with localcontext() as context:
        context.prec = max(28, len(parsed.as_tuple().digits) + 2, integer_digits + spec.minor_units + 2)
        return parsed.quantize(quantum, rounding=ROUND_HALF_UP)


def _exact_multiply(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2)
        return left * right


def _choice(random: Random, values: list[T]) -> T:
    # Deterministic synthetic data only; not used for secrets or cryptography.
    return random.choice(values)  # nosec B311


def _randint(random: Random, start: int, end: int) -> int:
    # Deterministic synthetic data only; not used for secrets or cryptography.
    return random.randint(start, end)  # nosec B311


def _uniform_decimal(random: Random, start: Decimal | int | str, end: Decimal | int | str) -> Decimal:
    # Deterministic synthetic data only; not used for secrets or cryptography.
    start_value = parse_amount(start, input_policy=STRICT_FINANCIAL_INPUT_POLICY)
    end_value = parse_amount(end, input_policy=STRICT_FINANCIAL_INPUT_POLICY)
    if start_value > end_value:
        raise ValueError("Synthetic decimal range start must not exceed its end.")
    factor = Decimal(10**SYNTHETIC_RANDOM_SCALE)
    with localcontext() as context:
        context.prec = max(
            28,
            len(start_value.as_tuple().digits) + SYNTHETIC_RANDOM_SCALE + 2,
            len(end_value.as_tuple().digits) + SYNTHETIC_RANDOM_SCALE + 2,
        )
        start_scaled = start_value * factor
        end_scaled = end_value * factor
    if start_scaled != start_scaled.to_integral_value() or end_scaled != end_scaled.to_integral_value():
        raise ValueError("Synthetic decimal range exceeds the generator scale.")
    step = _randint(random, int(start_scaled), int(end_scaled))
    sign = 1 if step < 0 else 0
    digits = tuple(int(character) for character in str(abs(step))) if step else (0,)
    return Decimal((sign, digits, -SYNTHETIC_RANDOM_SCALE))


def _rate_floor_count(rows: int, rate: Decimal) -> int:
    with localcontext() as context:
        context.prec = max(28, len(rate.as_tuple().digits) + len(str(abs(rows))) + 2)
        return int(Decimal(rows) * rate)


def _sha256_payload(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _currency_policy_payload(policy: ResolvedCurrencyPolicy) -> dict[str, object]:
    return {
        "currency": policy.spec.code,
        "minor_units": policy.spec.minor_units,
        "rounding_policy": policy.spec.rounding_policy,
        "currency_policy_digest": policy.policy_digest,
        "currency_registry_version": policy.registry_version,
        "currency_registry_digest": policy.registry_digest,
    }


def _output_file_record(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "bytes": len(content),
        "name": path.name,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _manifest_payload(
    *,
    rows: int,
    seed: int,
    industry: str,
    exception_rate: Decimal,
    critical_rate: Decimal,
    financial_input_policy: FinancialInputPolicy,
    currency_policy: ResolvedCurrencyPolicy,
    output_paths: list[Path],
) -> dict[str, object]:
    policy: dict[str, object] = {
        "algorithm_version": SYNTHETIC_GENERATOR_ALGORITHM_VERSION,
        "amount_random_scale": SYNTHETIC_RANDOM_SCALE,
        "critical_rate": canonical_decimal_text(critical_rate),
        "currency_policy": _currency_policy_payload(currency_policy),
        "exception_rate": canonical_decimal_text(exception_rate),
        "financial_input_policy": financial_input_policy,
        "industry": industry,
        "rows": rows,
        "seed": seed,
    }
    payload: dict[str, object] = {
        "schema_version": SYNTHETIC_GENERATOR_SCHEMA_VERSION,
        "policy": policy,
        "policy_digest": _sha256_payload(policy),
        "output_files": [_output_file_record(path) for path in sorted(output_paths, key=lambda item: item.name)],
    }
    payload["manifest_digest"] = _sha256_payload(payload)
    return payload


def verify_synthetic_manifest(payload: object, *, output_dir: Path | str | None = None) -> dict[str, object]:
    """Verify one exact-generator manifest and optionally its CSV bytes."""

    if not isinstance(payload, dict):
        raise ValueError("Synthetic manifest root must be an object.")
    expected_root = {"schema_version", "policy", "policy_digest", "output_files", "manifest_digest"}
    raw_schema_version = payload.get("schema_version")
    if (
        set(payload) != expected_root
        or isinstance(raw_schema_version, bool)
        or not isinstance(raw_schema_version, int)
        or raw_schema_version not in {1, SYNTHETIC_GENERATOR_SCHEMA_VERSION}
    ):
        raise ValueError("Synthetic manifest schema is unsupported or malformed.")
    policy = payload.get("policy")
    if not isinstance(policy, dict) or policy.get("algorithm_version") != SYNTHETIC_GENERATOR_ALGORITHM_VERSION:
        raise ValueError("Synthetic manifest policy is unsupported or malformed.")
    expected_policy = {
        "algorithm_version",
        "amount_random_scale",
        "critical_rate",
        "currency_policy",
        "exception_rate",
        "industry",
        "rows",
        "seed",
    }
    if raw_schema_version == SYNTHETIC_GENERATOR_SCHEMA_VERSION:
        expected_policy.add("financial_input_policy")
    if set(policy) != expected_policy or policy.get("amount_random_scale") != SYNTHETIC_RANDOM_SCALE:
        raise ValueError("Synthetic manifest policy is unsupported or malformed.")
    financial_input_policy: FinancialInputPolicy
    if raw_schema_version == 1:
        financial_input_policy = LEGACY_FINANCIAL_INPUT_POLICY
    else:
        try:
            financial_input_policy = validate_financial_input_policy(policy.get("financial_input_policy"))
        except InvalidAmountError as exc:
            raise ValueError("Synthetic manifest financial input policy is unsupported.") from exc
    for field_name in ("exception_rate", "critical_rate"):
        rate_text = policy.get(field_name)
        if not isinstance(rate_text, str):
            raise ValueError("Synthetic manifest rate policy is invalid.")
        parsed_rate = parse_generation_rate(
            rate_text,
            field_name=field_name,
            financial_input_policy=financial_input_policy,
        )
        if canonical_decimal_text(parsed_rate) != rate_text:
            raise ValueError("Synthetic manifest rate policy is not canonical.")
    if (
        isinstance(policy.get("rows"), bool)
        or not isinstance(policy.get("rows"), int)
        or int(policy["rows"]) < 1
        or isinstance(policy.get("seed"), bool)
        or not isinstance(policy.get("seed"), int)
        or str(policy.get("industry") or "") not in {"workshop", "manufacturing", "fleet", "dealership", "service"}
    ):
        raise ValueError("Synthetic manifest generation policy is invalid.")
    currency_policy = policy.get("currency_policy")
    expected_currency_fields = {
        "currency",
        "minor_units",
        "rounding_policy",
        "currency_policy_digest",
        "currency_registry_version",
        "currency_registry_digest",
    }
    if not isinstance(currency_policy, dict) or set(currency_policy) != expected_currency_fields:
        raise ValueError("Synthetic manifest currency policy is invalid.")
    currency_code = str(currency_policy.get("currency") or "")
    minor_units = currency_policy.get("minor_units")
    if (
        len(currency_code) != 3
        or not currency_code.isascii()
        or not currency_code.isalpha()
        or currency_code != currency_code.upper()
        or isinstance(minor_units, bool)
        or not isinstance(minor_units, int)
        or not 0 <= minor_units <= 8
        or currency_policy.get("rounding_policy") != "ROUND_HALF_UP"
    ):
        raise ValueError("Synthetic manifest currency policy is invalid.")
    for digest_name in ("currency_policy_digest", "currency_registry_digest"):
        digest_text = str(currency_policy.get(digest_name) or "")
        if len(digest_text) != 64 or any(character not in "0123456789abcdef" for character in digest_text):
            raise ValueError("Synthetic manifest currency digest is invalid.")
    registry_version = str(currency_policy.get("currency_registry_version") or "")
    if not 1 <= len(registry_version) <= 128:
        raise ValueError("Synthetic manifest currency registry version is invalid.")
    if payload.get("policy_digest") != _sha256_payload(policy):
        raise ValueError("Synthetic manifest policy digest verification failed.")
    unsigned = dict(payload)
    manifest_digest = unsigned.pop("manifest_digest")
    if manifest_digest != _sha256_payload(unsigned):
        raise ValueError("Synthetic manifest digest verification failed.")
    output_files = payload.get("output_files")
    if not isinstance(output_files, list) or len(output_files) != 8:
        raise ValueError("Synthetic manifest output file inventory is invalid.")
    seen: set[str] = set()
    root = Path(output_dir) if output_dir is not None else None
    for item in output_files:
        if not isinstance(item, dict) or set(item) != {"bytes", "name", "sha256"}:
            raise ValueError("Synthetic manifest output record is invalid.")
        name = str(item.get("name") or "")
        digest = str(item.get("sha256") or "")
        byte_count = item.get("bytes")
        if Path(name).name != name or not name.endswith(".csv") or name in seen:
            raise ValueError("Synthetic manifest output filename is invalid.")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("Synthetic manifest output digest is invalid.")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise ValueError("Synthetic manifest output byte count is invalid.")
        seen.add(name)
        if root is not None:
            path = root / name
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise ValueError("Synthetic manifest output file is unavailable.") from exc
            if len(content) != byte_count or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("Synthetic manifest output file verification failed.")
    if seen != _EXPECTED_OUTPUT_FILES:
        raise ValueError("Synthetic manifest output file inventory is invalid.")
    return payload


def generate_synthetic_dataset(
    rows: int,
    output_dir: Path | str,
    *,
    exception_rate: LegacyRateInput = "0.15",
    critical_rate: LegacyRateInput = "0.05",
    seed: int = 42,
    industry: str = "workshop",
    currency: str = "USD",
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> list[Path]:
    """Generate a realistic ERP-shaped synthetic dataset."""

    financial_input_policy = validate_financial_input_policy(financial_input_policy)
    exact_exception_rate = parse_generation_rate(
        exception_rate,
        field_name="exception_rate",
        financial_input_policy=financial_input_policy,
    )
    exact_critical_rate = parse_generation_rate(
        critical_rate,
        field_name="critical_rate",
        financial_input_policy=financial_input_policy,
    )
    currency_policy = CurrencyRegistry.resolve(currency)
    if rows < 1:
        raise ValueError("rows must be at least 1")
    profile = pick_profile(industry)
    # Deterministic synthetic data only; not used for secrets or cryptography.
    random = Random(seed)  # nosec B311
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    base_date = date(2026, 1, 1)

    product_count = max(12, min(rows // 20, 80))
    customer_count = max(10, min(rows // 25, 100))
    work_order_count = max(10, min(rows // 2, rows))

    products = []
    for index in range(1, product_count + 1):
        category = _choice(random, profile.categories)
        products.append(
            {
                "product_code": f"PRD-{index:04d}",
                "product_name": f"{category} Part {index:04d}",
                "category": category,
                "standard_cost": _money(_uniform_decimal(random, 15, 950), currency_policy),
                "currency": currency_policy.spec.code,
                "stock_account": "1400",
                "expense_account": "5100",
            },
        )

    customers = [
        {
            "customer_code": f"CUST-{index:04d}",
            "customer_name": f"Synthetic Customer {index:04d}",
            "segment": _choice(random, ["Fleet", "Dealer", "Industrial", "Manufacturing"]),
            "region": _choice(random, ["Cairo", "Alexandria", "Riyadh", "Dubai", "Casablanca"]),
        }
        for index in range(1, customer_count + 1)
    ]

    work_orders = []
    for index in range(1, work_order_count + 1):
        customer = _choice(random, customers)
        opened = base_date + timedelta(days=_randint(random, 0, 120))
        status = _choice(random, ["Open", "In Progress", "Closed", "Pending Invoice"])
        if index % 19 == 0:
            opened = base_date - timedelta(days=_randint(random, 95, 180))
            status = "Open"
        closed = opened + timedelta(days=_randint(random, 1, 12)) if status == "Closed" else ""
        actual_cost = _money(_uniform_decimal(random, 40, 2500), currency_policy)
        work_orders.append(
            {
                "work_order": f"WO-{index:05d}",
                "customer_code": customer["customer_code"],
                "customer_name": customer["customer_name"],
                "equipment_serial": f"EQ-{_randint(random, 1, customer_count * 3):05d}",
                "status": status,
                "opened_date": opened.isoformat(),
                "closed_date": closed.isoformat() if isinstance(closed, date) else "",
                "service_type": _choice(random, profile.service_types),
                "responsible_engineer": f"Engineer {_randint(random, 1, 25):02d}",
                "workshop": _choice(random, profile.workshops),
                "estimated_cost": _money(
                    _exact_multiply(actual_cost, _uniform_decimal(random, "0.8", "1.2")),
                    currency_policy,
                ),
                "actual_cost": actual_cost,
                "currency": currency_policy.spec.code,
            },
        )

    stock_moves = []
    gl_entries = []
    purchase_orders = []
    old_parts_returns = []
    invoices = []
    missing_stock_gl_count = 0
    exception_target = _rate_floor_count(rows, exact_exception_rate)

    for index in range(1, rows + 1):
        scenario = pick_scenario(random, exact_exception_rate, exact_critical_rate)
        work_order = _choice(random, work_orders)
        product = _choice(random, products)
        quantity = _randint(random, 1, 4)
        unit_cost = Decimal(str(product["standard_cost"]))
        total_cost = _money(_exact_multiply(Decimal(quantity), unit_cost), currency_policy)
        move_date = base_date + timedelta(days=_randint(random, 0, 150))
        source_document = f"STK-SYN-{index:06d}"
        movement_type = "ISSUE"
        warehouse = "MAIN"
        if scenario == "direct_fit":
            source_document = f"PO-SYN-{index:06d}"
            movement_type = "DIRECT_FIT"
            warehouse = "DIRECT"
            purchase_orders.append(
                {
                    "po_number": source_document,
                    "supplier_code": f"SUP-{_randint(random, 1, 30):04d}",
                    "supplier_name": f"Synthetic Supplier {_randint(random, 1, 30):04d}",
                    "po_date": (move_date - timedelta(days=1)).isoformat(),
                    "product_code": product["product_code"],
                    "quantity": quantity,
                    "unit_price": unit_cost,
                    "total_price": total_cost,
                    "currency": currency_policy.spec.code,
                    "status": "Approved",
                    "linked_work_order": work_order["work_order"],
                },
            )
        stock_moves.append(
            {
                "move_id": f"SM-SYN-{index:06d}",
                "date": move_date.isoformat(),
                "source_document": source_document if index != 7 else "STK-SYN-000001",
                "work_order": work_order["work_order"] if index != 11 else "WO-MISSING",
                "product_code": product["product_code"] if index != 13 else "PRD-MISSING",
                "product_name": product["product_name"],
                "category": product["category"],
                "quantity": quantity,
                "unit_cost": unit_cost,
                "total_cost": total_cost,
                "warehouse": warehouse,
                "movement_type": movement_type,
                "customer_code": work_order["customer_code"],
                "equipment_serial": work_order["equipment_serial"],
                "created_by": f"user_{_randint(random, 1, 8):02d}",
                "currency": currency_policy.spec.code,
            },
        )

        if scenario == "missing_gl":
            missing_stock_gl_count += 1
            continue

        gl_amount = total_cost
        gl_date = move_date
        gl_reference = source_document
        if scenario == "fuzzy_match":
            gl_reference = f"AUTO/{source_document}"
        elif scenario == "value_mismatch":
            gl_amount = _money(
                _exact_multiply(total_cost, _uniform_decimal(random, "0.8", "1.25")),
                currency_policy,
            )
        elif scenario == "date_mismatch":
            gl_date = move_date + timedelta(days=8)
        gl_entries.append(
            {
                "entry_id": f"GE-SYN-{index:06d}",
                "date": gl_date.isoformat(),
                "journal": "INV",
                "account_code": "5100",
                "account_name": "Spare parts expense",
                "reference": gl_reference,
                "source_document": f"JE-SYN-{index:06d}",
                "debit": gl_amount,
                "credit": 0,
                "amount": gl_amount,
                "cost_center": "WORKSHOP",
                "work_order": work_order["work_order"],
                "created_by": f"acct_{_randint(random, 1, 5):02d}",
                "currency": currency_policy.spec.code,
            },
        )

        if product["category"] in {"Brakes", "Electrical", "Engine", "Transmission"} and scenario != "missing_old_part":
            old_parts_returns.append(
                {
                    "return_id": f"RET-SYN-{index:06d}",
                    "work_order": work_order["work_order"],
                    "product_code": product["product_code"],
                    "returned_quantity": quantity,
                    "return_date": (move_date + timedelta(days=1)).isoformat(),
                    "received_by": f"stores_{_randint(random, 1, 4):02d}",
                    "condition": "Worn",
                },
            )

    extra_gl = max(1, exception_target - missing_stock_gl_count)
    for index in range(1, extra_gl + 1):
        work_order = _choice(random, work_orders)
        amount = _money(_uniform_decimal(random, 25, 700), currency_policy)
        gl_entries.append(
            {
                "entry_id": f"GE-EXTRA-{index:06d}",
                "date": (base_date + timedelta(days=_randint(random, 0, 150))).isoformat(),
                "journal": "MAN",
                "account_code": "5100",
                "account_name": "Spare parts expense",
                "reference": f"MANUAL-SYN-{index:06d}",
                "source_document": f"JE-EXTRA-{index:06d}",
                "debit": amount,
                "credit": 0,
                "amount": amount,
                "cost_center": "WORKSHOP",
                "work_order": work_order["work_order"],
                "created_by": "controller",
                "currency": currency_policy.spec.code,
            },
        )

    for index, work_order in enumerate(work_orders[: max(1, work_order_count // 2)], start=1):
        status = "Draft" if work_order["status"] == "Closed" and index % 3 == 0 else "Posted"
        invoices.append(
            {
                "invoice_number": f"INV-SYN-{index:06d}",
                "work_order": work_order["work_order"],
                "customer_code": work_order["customer_code"],
                "invoice_date": (base_date + timedelta(days=_randint(random, 15, 170))).isoformat(),
                "invoice_amount": _money(
                    _exact_multiply(
                        parse_amount(work_order["actual_cost"]),
                        _uniform_decimal(random, "1.05", "1.35"),
                    ),
                    currency_policy,
                ),
                "currency": currency_policy.spec.code,
                "status": status,
            },
        )

    if not purchase_orders:
        product = _choice(random, products)
        purchase_orders.append(
            {
                "po_number": "PO-SYN-BASE",
                "supplier_code": "SUP-0001",
                "supplier_name": "Synthetic Supplier 0001",
                "po_date": base_date.isoformat(),
                "product_code": product["product_code"],
                "quantity": 5,
                "unit_price": product["standard_cost"],
                "total_price": _money(
                    _exact_multiply(parse_amount(product["standard_cost"]), Decimal(5)),
                    currency_policy,
                ),
                "currency": currency_policy.spec.code,
                "status": "Received",
                "linked_work_order": "",
            },
        )

    outputs = {
        "stock_moves.csv": pd.DataFrame(stock_moves),
        "gl_entries.csv": pd.DataFrame(gl_entries),
        "work_orders.csv": pd.DataFrame(work_orders),
        "purchase_orders.csv": pd.DataFrame(purchase_orders),
        "products.csv": pd.DataFrame(products),
        "customers.csv": pd.DataFrame(customers),
        "old_parts_returns.csv": pd.DataFrame(old_parts_returns),
        "invoices.csv": pd.DataFrame(invoices),
    }
    paths: list[Path] = []
    for filename, frame in outputs.items():
        path = target / filename
        frame.to_csv(path, index=False, lineterminator="\n")
        paths.append(path)
    manifest = _manifest_payload(
        rows=rows,
        seed=seed,
        industry=profile.name,
        exception_rate=exact_exception_rate,
        critical_rate=exact_critical_rate,
        financial_input_policy=financial_input_policy,
        currency_policy=currency_policy,
        output_paths=paths,
    )
    (target / "synthetic_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paths
