from __future__ import annotations

import json
import re
from pathlib import Path

REQUIRED_DOCS = [
    Path("docs/support-playbook.md"),
    Path("docs/pilot-onboarding-checklist.md"),
    Path("docs/buyer-faq.md"),
    Path("docs/implementation-packages.md"),
    Path("docs/release-readiness-checklist.md"),
    Path("docs/security/security-questionnaire.md"),
]

REQUIRED_LINKS = [
    "docs/support-playbook.md",
    "docs/pilot-onboarding-checklist.md",
    "docs/buyer-faq.md",
    "docs/implementation-packages.md",
    "docs/release-readiness-checklist.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pilot_readiness_docs_exist_and_cover_required_boundaries() -> None:
    for path in REQUIRED_DOCS:
        assert path.exists(), path
        text = _read(path).lower()
        assert "local-first" in text, path
        assert "export-based" in text, path
        assert "no audit opinion" in text or "not issue or imply audit opinions" in text or "audit opinion" in text, path
        assert "compliance certification" in text, path

    combined = "\n".join(_read(path).lower() for path in REQUIRED_DOCS)
    assert "live customer data" in combined
    assert "do not share live customer data" in combined or "no live customer data sharing" in combined
    assert "direct erp connector" in combined
    assert "saas" in combined


def test_pilot_readiness_docs_avoid_unsupported_positive_claims() -> None:
    combined = "\n".join(_read(path).lower() for path in REQUIRED_DOCS)
    forbidden_patterns = [
        r"\btrusted by\b",
        r"\blogo wall\b",
        r"\btestimonial from\b",
        r"\bcustomer success story\b",
        r"\bguaranteed roi\b",
        r"\bguarantees? savings\b",
        r"\bsoc ?2 certified\b",
        r"\biso certified\b",
        r"\bsox compliant\b",
        r"\baudit opinion issued\b",
        r"\blegal signature support is implemented\b",
        r"\bdirect erp connectors? (are|is) (implemented|supported|available)\b",
        r"\bsaas (is|hosting is|platform is) (implemented|supported|available)\b",
        r"\breconforge (is|replaces|serves as) .*vendor replacement\b",
        r"\breconforge (is|provides|delivers) .*enterprise-ready\b",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, combined) is None, pattern

    assert "not supported" in combined
    assert "draft" in combined
    assert "non-contractual" in combined


def test_pilot_readiness_links_are_in_readme_and_docs_index() -> None:
    readme = _read(Path("README.md"))
    docs_index = _read(Path("docs/index.md"))

    for link in REQUIRED_LINKS:
        assert f"]({link})" in readme
        assert f"]({link.removeprefix('docs/')})" in docs_index


def test_pilot_readiness_templates_are_parseable_and_safe() -> None:
    template_paths = [
        Path("docs/support-intake-template.json"),
        Path("docs/pilot-success-criteria-template.json"),
    ]
    for path in template_paths:
        payload = json.loads(_read(path))
        text = json.dumps(payload, sort_keys=True).lower()
        assert payload["status"] == "draft_non_contractual"
        assert "live customer data" in text
        assert "do not share" in text or "no saas" in text
        assert "audit opinion" in text or "passwords" in text
