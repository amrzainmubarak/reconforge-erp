"""Malformed native dispatch arguments fail before command custody, even under -O."""
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("operation,fields", [
    ("receive-prepare", {"line_id": "original-line"}),
    ("receive-prepare", {}),
    ("invoice-match", {}),
    ("invoice-post", {"document_id": "original-invoice"}),
    ("invoice-post", {"expected_budget_version": 1}),
])
@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
def test_invalid_dispatch_never_reaches_command_or_native_owner(
    tmp_path: Path, operation: str, fields: dict[str, object], optimized: bool,
) -> None:
    # Isolate only the argument boundary. The real original receipt/AP cycle
    # separately verifies current authority, native effects and rollback.
    root = Path(__file__).resolve().parents[1]
    probe = tmp_path / "argument-guard.py"
    probe.write_text(f"""import sys
sys.path.insert(0, {str(root)!r})
from contextlib import nullcontext
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_manufacturing_supply_plan import PostgresManufacturingSupplyPlanRepository
owner = PostgresManufacturingSupplyPlanRepository(None, 'synthetic-argument-boundary')
owner._transaction = lambda: nullcontext()
owner._row = lambda identifier: {{'id': identifier}}
owner._actor = lambda *args, **kwargs: None
def forbidden(*args, **kwargs):
    raise RuntimeError('command_or_native_owner_reached')
owner._command = forbidden
try:
    owner.procurement_operation('original-plan', 'original-purchase', {operation!r},
        expected_version=1, command_id='malformed-input', reason='Required original arguments',
        actor=None, **{fields!r})
except FinancePostingError as exc:
    if exc.code != 'manufacturing_execution_invalid':
        raise RuntimeError('wrong_public_error') from exc
else:
    raise RuntimeError('malformed_input_admitted')
""")
    completed = subprocess.run([sys.executable, "-I", *(["-O"] if optimized else []), str(probe)],
                               capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
