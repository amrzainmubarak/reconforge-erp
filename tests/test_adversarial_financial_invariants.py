"""Adversarial Financial Invariants Suite.

Validates:
1. Static AST scanner: Walks AST of all .py files in reconforge/domain/, reconforge/packs/,
   and financial infrastructure, ensuring zero float literals, zero from_float calls,
   and zero floating-point division in financial effect paths.
2. Multi-register asset disposal property tests: Fuzzes 1,000 asset acquisitions across
   5 distinct books/registers (IFRS, Tax, Local Statutory, Insurance, Management),
   verifying sum(Debit) == sum(Credit), non-negative carrying values, and exact gain/loss allocation.
3. Non-divisible remainder conservation: Proves zero penny leakage using the Largest-Remainder
   (Hare-Niemeyer) allocation algorithm across randomized multi-item distributions.
"""

from __future__ import annotations

import ast
import os
import random
from decimal import Decimal
from pathlib import Path

import pytest

from reconforge.domain.fixed_assets import (
    AssetRegister,
    AssetRegisterState,
    MultiRegisterAssetAcquisition,
    cumulative_depreciation,
    multi_register_disposal_lines,
)

ROOT = Path(__file__).resolve().parents[1]


# ==============================================================================
# 1. AST Float & Division Scanner
# ==============================================================================


def _collect_py_files(directory: Path) -> list[Path]:
    """Collect all python source files under a directory recursively."""
    py_files: list[Path] = []
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith(".py"):
                py_files.append(Path(root) / f)
    return sorted(py_files)


def test_ast_zero_float_in_domain_files() -> None:
    """Every .py file in reconforge/domain/ must contain 0 float literals and 0 from_float calls."""
    domain_dir = ROOT / "reconforge" / "domain"
    py_files = _collect_py_files(domain_dir)
    assert len(py_files) > 20, f"Expected domain files, found {len(py_files)}"

    float_violations: list[tuple[str, int, float]] = []
    from_float_violations: list[tuple[str, int]] = []

    for path in py_files:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
        rel_path = path.relative_to(ROOT).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                float_violations.append((rel_path, node.lineno, node.value))
            if isinstance(node, ast.Attribute) and node.attr == "from_float":
                from_float_violations.append((rel_path, node.lineno))

    assert not float_violations, (
        f"Detected {len(float_violations)} float literal(s) in domain code: {float_violations}"
    )
    assert not from_float_violations, (
        f"Detected {len(from_float_violations)} from_float call(s) in domain code: {from_float_violations}"
    )


def test_ast_zero_float_in_packs_files() -> None:
    """Every .py file in reconforge/packs/ must contain 0 float literals and 0 from_float calls."""
    packs_dir = ROOT / "reconforge" / "packs"
    py_files = _collect_py_files(packs_dir)
    assert len(py_files) > 5, f"Expected pack files, found {len(py_files)}"

    float_violations: list[tuple[str, int, float]] = []
    from_float_violations: list[tuple[str, int]] = []

    for path in py_files:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
        rel_path = path.relative_to(ROOT).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                float_violations.append((rel_path, node.lineno, node.value))
            if isinstance(node, ast.Attribute) and node.attr == "from_float":
                from_float_violations.append((rel_path, node.lineno))

    assert not float_violations, (
        f"Detected {len(float_violations)} float literal(s) in packs code: {float_violations}"
    )
    assert not from_float_violations, (
        f"Detected {len(from_float_violations)} from_float call(s) in packs code: {from_float_violations}"
    )


def test_ast_zero_float_in_financial_infrastructure() -> None:
    """All financial posting, inventory, settlement, and reconciliation infrastructure files

    must contain 0 float literals, 0 from_float calls, and 0 ast.Div operators.
    """
    infra_dir = ROOT / "reconforge" / "infrastructure"
    financial_infra_filenames = {
        "postgres_finance_posting.py",
        "postgres_customer_partial_returns.py",
        "postgres_fixed_assets.py",
        "postgres_inventory_valuation.py",
        "postgres_intercompany.py",
        "postgres_settlement.py",
        "postgres_treasury.py",
        "postgres_consolidated_statements.py",
        "postgres_consolidation_close.py",
        "postgres_consolidation_deferred_tax.py",
        "sqlite_finance_posting.py",
        "sqlite_customer_partial_returns.py",
        "sqlite_fixed_assets.py",
        "sqlite_inventory_valuation.py",
        "sqlite_settlement.py",
    }

    found_files = 0
    for filename in financial_infra_filenames:
        path = infra_dir / filename
        if not path.is_file():
            continue
        found_files += 1
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
        rel_path = path.relative_to(ROOT).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                pytest.fail(f"Float literal {node.value} at {rel_path}:{node.lineno}")
            if isinstance(node, ast.Attribute) and node.attr == "from_float":
                pytest.fail(f"from_float attribute access at {rel_path}:{node.lineno}")
            if isinstance(node, ast.Div):
                pytest.fail(f"ast.Div operator at {rel_path}:{getattr(node, 'lineno', 0)}")

    assert found_files >= 5, f"Expected at least 5 financial infrastructure files, found {found_files}"


def test_ast_division_in_domain_is_strictly_controlled() -> None:
    """In reconforge/domain/, floating-point division is forbidden.

    The only allowed ast.Div node is in control_scores.py where Decimal division is executed
    under explicit localcontext precision.
    """
    domain_dir = ROOT / "reconforge" / "domain"
    py_files = _collect_py_files(domain_dir)

    div_files: dict[str, list[int]] = {}
    for path in py_files:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
        rel_path = path.relative_to(ROOT).as_posix()

        lines: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Div):
                lines.append(getattr(node, "lineno", 0))
        if lines:
            div_files[rel_path] = lines

    # Only control_scores.py uses Decimal division with quantize
    for file_path in div_files:
        assert file_path.endswith("control_scores.py"), (
            f"Unauthorized ast.Div operator in domain file {file_path} at lines {div_files[file_path]}"
        )


# ==============================================================================
# 2. Multi-Register Fixed Asset Disposal Property Tests (Fuzzing 1,000 cases)
# ==============================================================================


def test_multi_register_disposal_property_1000_fuzz() -> None:
    """Property test fuzzing 1,000 asset acquisitions across 5 distinct books/registers.

    Asserts:
    1. sum(Debit) == sum(Credit) across all registers with 0 float.
    2. Carrying value >= salvage value before disposal (or 0 if impaired).
    3. Gain/Loss strictly matches independent Decimal calculation.
    """
    rng = random.Random(20261019)
    register_codes = ["IFRS", "TAX", "LOCAL_STATUTORY", "INSURANCE", "MANAGEMENT"]

    for trial in range(1000):
        # Generate asset acquisition
        useful_life_months = rng.randint(12, 360)
        cost_minor = rng.randint(10_000, 50_000_000)  # $100.00 to $500,000.00
        salvage_minor = rng.randint(0, cost_minor // 4)

        registers: list[AssetRegister] = []
        states: dict[str, AssetRegisterState] = {}

        for reg_code in register_codes:
            # Vary cost/salvage slightly per register (tax book may have different basis)
            reg_cost = cost_minor + rng.randint(-500, 500)
            reg_salvage = min(salvage_minor, reg_cost // 5)
            reg_life = max(12, useful_life_months + rng.randint(-6, 6))

            reg = AssetRegister(
                register_code=reg_code,
                cost_minor=reg_cost,
                salvage_minor=reg_salvage,
                useful_life_months=reg_life,
                asset_account_code=f"1500.{reg_code}",
                accumulated_depreciation_account_code=f"1550.{reg_code}",
                accumulated_impairment_account_code=f"1560.{reg_code}",
                depreciation_expense_account_code=f"6500.{reg_code}",
                impairment_loss_account_code=f"6510.{reg_code}",
                gain_account_code=f"4900.{reg_code}",
                loss_account_code=f"7900.{reg_code}",
            )
            registers.append(reg)

            # Elapsed months depreciated
            months_depreciated = rng.randint(0, reg_life)
            accum_depr = cumulative_depreciation(reg_cost, reg_salvage, reg_life, months_depreciated)

            # Optional impairment
            max_impair = reg_cost - accum_depr - reg_salvage
            accum_impair = rng.randint(0, max_impair) if max_impair > 0 and rng.random() < 0.2 else 0

            state = AssetRegisterState.create(
                reg,
                accumulated_depreciation_minor=accum_depr,
                accumulated_impairment_minor=accum_impair,
                months_depreciated=months_depreciated,
            )
            assert state.carrying_value_minor >= reg_salvage, (
                f"Trial {trial} [{reg_code}]: carrying {state.carrying_value_minor} < salvage {reg_salvage}"
            )
            states[reg_code] = state

        asset = MultiRegisterAssetAcquisition(
            workspace_id="ws-fuzz",
            organization_id="org-fuzz",
            legal_entity_id="entity-fuzz",
            organization_code="ORG-01",
            entity_code="ENT-01",
            asset_number=f"AST-FUZZ-{trial:04d}",
            name=f"Fuzz Asset {trial}",
            journal_code="GEN",
            period_id="2026-01",
            posting_date="2026-01-01",
            in_service_date="2026-01-01",
            registers=tuple(registers),
            cash_account_code="1010.CASH",
        )

        # Randomized proceeds: $0, below carrying (loss), exact carrying, or above carrying (gain)
        proceeds_mode = rng.choice(["zero", "loss", "exact", "gain"])
        primary_carrying = states["IFRS"].carrying_value_minor

        if proceeds_mode == "zero":
            proceeds_minor = 0
        elif proceeds_mode == "loss":
            proceeds_minor = rng.randint(1, max(1, primary_carrying - 1)) if primary_carrying > 1 else 0
        elif proceeds_mode == "exact":
            proceeds_minor = primary_carrying
        else:
            proceeds_minor = primary_carrying + rng.randint(1, 10_000_000)

        # Call multi-register disposal lines generator
        disposal_result = multi_register_disposal_lines(
            asset=asset,
            states=states,
            proceeds_minor=proceeds_minor,
            proceeds_cash_account="1010.CASH",
        )

        assert len(disposal_result) == 5, f"Expected 5 registers in disposal result, got {len(disposal_result)}"

        for reg_code, lines in disposal_result.items():
            debit_total = sum(line["debit_minor"] for line in lines)
            credit_total = sum(line["credit_minor"] for line in lines)

            # Invariant 1: Double-entry balancing Debit == Credit
            assert debit_total == credit_total, (
                f"Trial {trial} [{reg_code}]: Unbalanced lines! Debit {debit_total} != Credit {credit_total}"
            )

            # Invariant 2: Gain or Loss matches Decimal calculation
            reg_carrying = states[reg_code].carrying_value_minor
            expected_gain_or_loss = Decimal(proceeds_minor) - Decimal(reg_carrying)

            gain_lines = [line for line in lines if line["account_code"] == f"4900.{reg_code}"]
            loss_lines = [line for line in lines if line["account_code"] == f"7900.{reg_code}"]

            if expected_gain_or_loss > 0:
                assert len(gain_lines) == 1, f"Trial {trial} [{reg_code}]: Missing gain line"
                assert len(loss_lines) == 0, f"Trial {trial} [{reg_code}]: Unexpected loss line"
                assert gain_lines[0]["credit_minor"] == int(expected_gain_or_loss)
            elif expected_gain_or_loss < 0:
                assert len(loss_lines) == 1, f"Trial {trial} [{reg_code}]: Missing loss line"
                assert len(gain_lines) == 0, f"Trial {trial} [{reg_code}]: Unexpected gain line"
                assert loss_lines[0]["debit_minor"] == int(abs(expected_gain_or_loss))
            else:
                assert len(gain_lines) == 0
                assert len(loss_lines) == 0


# ==============================================================================
# 3. Non-Divisible Remainder Conservation (Largest-Remainder Method / Hare-Niemeyer)
# ==============================================================================


def largest_remainder_allocation(
    total_amount_minor: int,
    weights: list[int],
) -> list[int]:
    """Apportion total_amount_minor across items using the Largest-Remainder (Hare-Niemeyer) algorithm.

    Guarantees:
    1. sum(allocations) == total_amount_minor exactly (zero penny leakage).
    2. Every allocated amount is a non-negative integer.
    3. Deterministic tie-breaking by original index.
    """
    if type(total_amount_minor) is not int or total_amount_minor < 0:
        raise ValueError("total_amount_minor must be a non-negative integer")
    if not weights or any(type(w) is not int or w < 0 for w in weights):
        raise ValueError("weights must be non-empty list of non-negative integers")

    total_weight = sum(weights)
    if total_weight == 0:
        if total_amount_minor == 0:
            return [0] * len(weights)
        raise ValueError("Cannot allocate positive amount with zero total weight")

    # Step 1: Compute floor quotas and exact integer remainders
    # quota_i = (total_amount_minor * w_i) / total_weight
    # In integer arithmetic: quotient, remainder = divmod(total * w_i, total_weight)
    floors: list[int] = []
    remainders: list[tuple[int, int]] = []  # (remainder, index)

    for i, w in enumerate(weights):
        q, r = divmod(total_amount_minor * w, total_weight)
        floors.append(q)
        remainders.append((r, i))

    shortfall = total_amount_minor - sum(floors)
    assert 0 <= shortfall < len(weights), f"Shortfall {shortfall} out of bounds"

    # Step 2: Sort by largest remainder descending, tie-breaking by index ascending
    remainders.sort(key=lambda item: (-item[0], item[1]))

    # Step 3: Distribute +1 minor unit to the top `shortfall` items
    allocated = list(floors)
    for k in range(shortfall):
        idx = remainders[k][1]
        allocated[idx] += 1

    return allocated


def test_largest_remainder_zero_penny_leakage_property() -> None:
    """Randomized property test for non-divisible remainder conservation.

    Fuzzes 1,000 distributions with varying item counts (2 to 50 items)
    and amounts up to $10,000,000.00 (1,000,000,000 minor units).
    Verifies that sum(allocated) strictly equals total_amount_minor in 100% of cases.
    """
    rng = random.Random(42)

    for _ in range(1000):
        item_count = rng.randint(2, 50)
        total_minor = rng.randint(0, 1_000_000_000)
        weights = [rng.randint(1, 1000) for _ in range(item_count)]

        allocated = largest_remainder_allocation(total_minor, weights)

        # Invariant 1: Sum of allocations must equal total amount with zero leakage
        assert sum(allocated) == total_minor, (
            f"Zero-penny leakage violation! sum({allocated}) = {sum(allocated)} != {total_minor}"
        )

        # Invariant 2: All items receive non-negative integer minor units
        assert all(isinstance(x, int) and x >= 0 for x in allocated)

        # Invariant 3: Quota bounds check
        total_weight = sum(weights)
        for i, (alloc, w) in enumerate(zip(allocated, weights, strict=True)):
            exact_quota = (Decimal(total_minor) * Decimal(w)) / Decimal(total_weight)
            floor_quota = int(exact_quota)
            assert alloc in (floor_quota, floor_quota + 1), (
                f"Item {i}: alloc {alloc} not within [floor, floor+1] for quota {exact_quota}"
            )
