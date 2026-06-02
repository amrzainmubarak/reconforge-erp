"""Synthetic ERP dataset generator."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from random import Random

import pandas as pd

from reconforge.generator.scenarios import pick_profile, pick_scenario


def _money(value: float) -> float:
    return round(value, 2)


def generate_synthetic_dataset(
    rows: int,
    output_dir: Path | str,
    *,
    exception_rate: float = 0.15,
    critical_rate: float = 0.05,
    seed: int = 42,
    industry: str = "workshop",
    currency: str = "USD",
) -> list[Path]:
    """Generate a realistic ERP-shaped synthetic dataset."""

    random = Random(seed)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    profile = pick_profile(industry)
    base_date = date(2026, 1, 1)

    product_count = max(12, min(rows // 20, 80))
    customer_count = max(10, min(rows // 25, 100))
    work_order_count = max(10, min(rows // 2, rows))

    products = []
    for index in range(1, product_count + 1):
        category = random.choice(profile.categories)
        products.append(
            {
                "product_code": f"PRD-{index:04d}",
                "product_name": f"{category} Part {index:04d}",
                "category": category,
                "standard_cost": _money(random.uniform(15, 950)),
                "stock_account": "1400",
                "expense_account": "5100",
            },
        )

    customers = [
        {
            "customer_code": f"CUST-{index:04d}",
            "customer_name": f"Synthetic Customer {index:04d}",
            "segment": random.choice(["Fleet", "Dealer", "Industrial", "Manufacturing"]),
            "region": random.choice(["Cairo", "Alexandria", "Riyadh", "Dubai", "Casablanca"]),
        }
        for index in range(1, customer_count + 1)
    ]

    work_orders = []
    for index in range(1, work_order_count + 1):
        customer = random.choice(customers)
        opened = base_date + timedelta(days=random.randint(0, 120))
        status = random.choice(["Open", "In Progress", "Closed", "Pending Invoice"])
        if index % 19 == 0:
            opened = base_date - timedelta(days=random.randint(95, 180))
            status = "Open"
        closed = opened + timedelta(days=random.randint(1, 12)) if status == "Closed" else ""
        actual_cost = _money(random.uniform(40, 2500))
        work_orders.append(
            {
                "work_order": f"WO-{index:05d}",
                "customer_code": customer["customer_code"],
                "customer_name": customer["customer_name"],
                "equipment_serial": f"EQ-{random.randint(1, customer_count * 3):05d}",
                "status": status,
                "opened_date": opened.isoformat(),
                "closed_date": closed.isoformat() if isinstance(closed, date) else "",
                "service_type": random.choice(profile.service_types),
                "responsible_engineer": f"Engineer {random.randint(1, 25):02d}",
                "workshop": random.choice(profile.workshops),
                "estimated_cost": _money(actual_cost * random.uniform(0.8, 1.2)),
                "actual_cost": actual_cost,
            },
        )

    stock_moves = []
    gl_entries = []
    purchase_orders = []
    old_parts_returns = []
    invoices = []
    missing_stock_gl_count = 0
    exception_target = int(rows * exception_rate)

    for index in range(1, rows + 1):
        scenario = pick_scenario(random, exception_rate, critical_rate)
        work_order = random.choice(work_orders)
        product = random.choice(products)
        quantity = random.randint(1, 4)
        unit_cost = float(str(product["standard_cost"]))
        total_cost = _money(quantity * unit_cost)
        move_date = base_date + timedelta(days=random.randint(0, 150))
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
                    "supplier_code": f"SUP-{random.randint(1, 30):04d}",
                    "supplier_name": f"Synthetic Supplier {random.randint(1, 30):04d}",
                    "po_date": (move_date - timedelta(days=1)).isoformat(),
                    "product_code": product["product_code"],
                    "quantity": quantity,
                    "unit_price": unit_cost,
                    "total_price": total_cost,
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
                "created_by": f"user_{random.randint(1, 8):02d}",
                "currency": currency,
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
            gl_amount = _money(total_cost * random.uniform(0.8, 1.25))
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
                "created_by": f"acct_{random.randint(1, 5):02d}",
                "currency": currency,
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
                    "received_by": f"stores_{random.randint(1, 4):02d}",
                    "condition": "Worn",
                },
            )

    extra_gl = max(1, exception_target - missing_stock_gl_count)
    for index in range(1, extra_gl + 1):
        work_order = random.choice(work_orders)
        amount = _money(random.uniform(25, 700))
        gl_entries.append(
            {
                "entry_id": f"GE-EXTRA-{index:06d}",
                "date": (base_date + timedelta(days=random.randint(0, 150))).isoformat(),
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
                "currency": currency,
            },
        )

    for index, work_order in enumerate(work_orders[: max(1, work_order_count // 2)], start=1):
        status = "Draft" if work_order["status"] == "Closed" and index % 3 == 0 else "Posted"
        invoices.append(
            {
                "invoice_number": f"INV-SYN-{index:06d}",
                "work_order": work_order["work_order"],
                "customer_code": work_order["customer_code"],
                "invoice_date": (base_date + timedelta(days=random.randint(15, 170))).isoformat(),
                "invoice_amount": _money(float(str(work_order["actual_cost"])) * random.uniform(1.05, 1.35)),
                "status": status,
            },
        )

    if not purchase_orders:
        product = random.choice(products)
        purchase_orders.append(
            {
                "po_number": "PO-SYN-BASE",
                "supplier_code": "SUP-0001",
                "supplier_name": "Synthetic Supplier 0001",
                "po_date": base_date.isoformat(),
                "product_code": product["product_code"],
                "quantity": 5,
                "unit_price": product["standard_cost"],
                "total_price": _money(float(str(product["standard_cost"])) * 5),
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
        frame.to_csv(path, index=False)
        paths.append(path)
    return paths
