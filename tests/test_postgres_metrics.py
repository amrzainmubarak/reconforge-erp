from __future__ import annotations

from tests.test_application_metrics import (
    test_live_postgres_metrics_and_sqlite_parity,
)

__all__ = ["test_live_postgres_metrics_and_sqlite_parity"]

# Historical CI paths imported this module as `tests/test_postgres_metrics.py`.
# The implementation now lives in `tests/test_application_metrics.py`; keep this
# shim so older workflow paths continue to resolve without changing behavior.
