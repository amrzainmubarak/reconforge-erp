from __future__ import annotations

import re
import tomllib
from pathlib import Path

RELEASE_VERSION = "0.7.0"

REQUIRED_DOCS = [
    Path("docs/releases/v0.7.0.md"),
    Path("docs/deployment-smoke-check.md"),
    Path("docs/docker-verification.md"),
    Path("docs/release-readiness-checklist.md"),
]

REQUIRED_SMOKE_COMMANDS = [
    "python -m ruff check .",
    "python -m mypy reconforge",
    "python -m pytest",
    "python -m bandit -q -r reconforge",
    "python -m reconforge.cli doctor",
    "git diff --check",
    "reconforge demo run --output output/demo",
    "reconforge demo enterprise --output output/enterprise_demo",
    "reconforge db init --db output/reconforge.db",
    "reconforge api serve --db output/reconforge.db --host 127.0.0.1 --port 8765",
    "reconforge studio --input examples/sample_data --output output/demo",
    "reconforge studio --input examples/sample_data --output output/demo --db output/reconforge.db --require-auth",
    "docker build -t reconforge-erp .",
    "docker run --rm reconforge-erp reconforge doctor",
    "docker run --rm -v ${PWD}/output:/app/output reconforge-erp reconforge demo run --output output/demo",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_readiness_docs_exist_and_cover_release_positioning() -> None:
    for path in REQUIRED_DOCS:
        assert path.exists(), path

    release_note = _read(Path("docs/releases/v0.7.0.md")).lower()
    for phrase in [
        "foundation-stage",
        "local-first",
        "export-based",
        "pilot evaluation",
        "self-hosted/local-capable foundations",
    ]:
        assert phrase in release_note

    demo_page = _read(Path("docs/website/demo-page.md")).lower()
    assert "sample or synthetic data" in demo_page
    assert "do not use live customer data" in demo_page
    assert "synthetic enterprise demo" in release_note


def test_deployment_smoke_docs_include_required_commands_and_docker_boundary() -> None:
    combined = "\n".join(_read(path) for path in REQUIRED_DOCS)
    for command in REQUIRED_SMOKE_COMMANDS:
        assert command in combined, command

    lower = combined.lower()
    assert "docker runtime verification depends on local docker availability" in lower
    assert "do not claim docker runtime verification unless these commands pass" in lower
    assert "local long-running server checks" in lower or "long-running local server commands" in lower


def test_release_claim_checklists_cover_required_boundaries() -> None:
    combined = "\n".join(_read(path).lower() for path in REQUIRED_DOCS)
    for boundary in [
        "no enterprise-ready claim",
        "no compliance certification claim",
        "no audit opinion claim",
        "no legal signature claim",
        "no direct connector claim",
        "no production saas claim",
    ]:
        assert boundary in combined
    assert "no real customer" in combined
    assert "roi" in combined
    assert "testimonial" in combined


def test_release_docs_avoid_unsupported_positive_claims() -> None:
    combined = "\n".join(
        _read(path).lower()
        for path in [
            Path("docs/releases/v0.7.0.md"),
            Path("docs/deployment-smoke-check.md"),
            Path("docs/docker-verification.md"),
            Path("CHANGELOG.md"),
            Path("README.md"),
        ]
    )
    forbidden_patterns = [
        r"\breconforge(?: erp)? is enterprise-ready\b",
        r"\benterprise-ready release\b",
        r"\bproduction saas (is|release|platform|service)\b",
        r"\bsoc ?2 certified\b",
        r"\biso certified\b",
        r"\bsox compliant\b",
        r"\bbig 4 approved\b",
        r"\baudit opinion issued\b",
        r"\blegal signature support is implemented\b",
        r"\bdirect erp connectors? (are|is) (implemented|supported|available)\b",
        r"\bcustomer testimonials\b",
        r"\breal customer traction\b",
        r"\bproven roi\b",
        r"\bguaranteed roi\b",
        r"\bvendor replacement\b",
        r"\breplacement for blackline\b",
        r"\breplacement for floqast\b",
        r"\breplacement for workiva\b",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, combined) is None, pattern


def test_version_references_are_consistent_for_v070_release() -> None:
    pyproject = tomllib.loads(_read(Path("pyproject.toml")))
    assert pyproject["project"]["version"] == RELEASE_VERSION
    assert f'version="{RELEASE_VERSION}"' in _read(Path("setup.py"))
    assert f'__version__ = "{RELEASE_VERSION}"' in _read(Path("reconforge/__init__.py"))

    for path in [
        Path("README.md"),
        Path("docs/index.md"),
        Path("CHANGELOG.md"),
        Path("docs/releases/v0.7.0.md"),
    ]:
        assert f"v{RELEASE_VERSION}" in _read(path), path

    assert "version=__version__" in _read(Path("reconforge/dashboard/app.py"))
    assert "version=__version__" in _read(Path("reconforge/studio/app.py"))


def test_docs_index_and_readme_link_release_smoke_docs() -> None:
    docs_index = _read(Path("docs/index.md"))
    readme = _read(Path("README.md"))

    for link in [
        "releases/v0.7.0.md",
        "deployment-smoke-check.md",
        "docker-verification.md",
    ]:
        assert f"]({link})" in docs_index

    for link in [
        "docs/releases/v0.7.0.md",
        "docs/deployment-smoke-check.md",
        "docs/docker-verification.md",
    ]:
        assert f"]({link})" in readme
