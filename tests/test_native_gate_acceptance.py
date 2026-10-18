"""Mandatory PostgreSQL execution cannot be accepted from an empty/skip packet."""

import importlib.util
from pathlib import Path
from xml.etree.ElementTree import ParseError

import pytest
from defusedxml.common import DefusedXmlException


def validator():
    path = Path(__file__).resolve().parents[1] / ".github/scripts/verify_commercial_collections.py"
    spec = importlib.util.spec_from_file_location("native_acceptance_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.require_native_acceptance


def packet(cases: str, *, tests: int = 1, failures: int = 0, errors: int = 0, skipped: int = 0) -> str:
    return (f'<testsuites><testsuite tests="{tests}" failures="{failures}" errors="{errors}" '
            f'skipped="{skipped}">{cases}</testsuite></testsuites>')


def test_acceptance_requires_actual_native_case_execution() -> None:
    counts = validator()(packet('<testcase name="reviewed_partial_payment"/>'))
    assert counts == {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}


@pytest.mark.parametrize("document", [
    None, "", "<testsuites/>", packet("", tests=0), packet("", tests=1),
    packet('<testcase><skipped/></testcase>', skipped=1),
    packet('<testcase><failure/></testcase>', failures=1),
    packet('<testcase><error/></testcase>', errors=1),
    packet('<testcase><skipped/></testcase>'),
    packet('<testcase/>', tests=2),
    '<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///private">]><testsuites>&secret;</testsuites>',
])
def test_missing_skipped_failed_or_inconsistent_native_evidence_is_refused(document: str | None) -> None:
    with pytest.raises((ValueError, ParseError, DefusedXmlException)):
        validator()(document)
