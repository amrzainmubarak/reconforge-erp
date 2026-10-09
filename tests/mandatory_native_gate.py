"""Explicit CI-only admission for mandatory native pytest evidence.

Load with ``PYTEST_ADDOPTS='-p tests.mandatory_native_gate'``. Unconfigured
optional local suites keep their existing prerequisite behavior.
"""

import sys
from collections.abc import Mapping

import pytest


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Reject incomplete evidence without replacing an existing failure code."""
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    stats = getattr(terminal, "stats", None)
    available = isinstance(stats, Mapping)
    counts = {category: len(stats.get(category, ())) if available else 0
              for category in ("skipped", "xfailed", "xpassed")}
    collected = session.testscollected
    invalid = not available or collected == 0 or any(counts.values())
    if invalid and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    summary = (f"mandatory native gate: collected={collected}, skipped={counts['skipped']}, "
               f"xfailed={counts['xfailed']}, xpassed={counts['xpassed']}, stats_available={int(available)}")
    if terminal is not None:
        terminal.write_sep("=", summary)
    else:
        sys.stderr.write(summary + "\n")

