from __future__ import annotations

import re
from pathlib import Path

WEBSITE_DOCS = [
    Path("docs/website/homepage-copy.md"),
    Path("docs/website/product-pages.md"),
    Path("docs/website/demo-page.md"),
    Path("docs/website/github-launch-post.md"),
    Path("docs/website/release-announcement-draft.md"),
    Path("docs/website/social-launch-snippets.md"),
    Path("docs/website/claim-boundary-guide.md"),
]

LAUNCH_COPY_DOCS = [path for path in WEBSITE_DOCS if path.name != "claim-boundary-guide.md"]

DOCS_INDEX_LINKS = [
    "website/homepage-copy.md",
    "website/product-pages.md",
    "website/demo-page.md",
    "website/github-launch-post.md",
    "website/release-announcement-draft.md",
    "website/social-launch-snippets.md",
    "website/claim-boundary-guide.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_website_launch_copy_docs_exist_and_cover_positioning() -> None:
    for path in WEBSITE_DOCS:
        assert path.exists(), path
        text = _read(path).lower()
        assert "local-first" in text, path
        assert "export-based" in text, path

    combined = "\n".join(_read(path).lower() for path in WEBSITE_DOCS)
    assert "synthetic enterprise demo" in combined
    assert "pilot-ready open-source toolkit for local evaluation" in combined
    assert "finance controls platform foundations" in combined


def test_website_launch_copy_mentions_demo_and_assurance_boundaries() -> None:
    combined = "\n".join(_read(path).lower() for path in LAUNCH_COPY_DOCS)
    assert "reconforge demo run --output output/demo" in combined
    assert "reconforge demo enterprise --output output/enterprise_demo" in combined
    assert "all demo data is synthetic" in combined or "all public demo material should use sample or synthetic data" in combined
    assert "no audit opinion" in combined
    assert "compliance certification" in combined
    assert "no fake" in combined or "do not add fake" in combined


def test_website_launch_copy_avoids_unsupported_positive_claims() -> None:
    combined = "\n".join(_read(path).lower() for path in LAUNCH_COPY_DOCS)
    forbidden_patterns = [
        r"\benterprise-ready\b",
        r"\bsox compliant\b",
        r"\bsoc ?2 certified\b",
        r"\biso certified\b",
        r"\bbig 4 approved\b",
        r"\bblackline replacement\b",
        r"\bfloqast replacement\b",
        r"\bworkiva replacement\b",
        r"\blegal signature support is implemented\b",
        r"\bnon-repudiation controls are implemented\b",
        r"\bguaranteed compliance\b",
        r"\bproduction saas\b(?! claim)",
        r"\bdirect erp connector suite\b",
        r"\breal customer traction\b",
        r"\bproven roi\b",
        r"\btrusted by\b",
        r"\bcustomer logos are shown\b",
        r"\bcustomer testimonials\b",
        r"\brevenue traction\b",
        r"\bguaranteed savings\b",
        r"\bvendor replacement\b",
        r"\breplacement for blackline\b",
        r"\breplacement for floqast\b",
        r"\breplacement for workiva\b",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, combined) is None, pattern


def test_claim_boundary_guide_contains_allowed_and_forbidden_wording() -> None:
    guide = _read(Path("docs/website/claim-boundary-guide.md"))
    lower = guide.lower()
    for allowed in [
        "local-first",
        "export-based",
        "self-hosted/local-capable foundations",
        "pilot-ready open-source toolkit for local evaluation",
        "finance controls platform foundations",
        "synthetic enterprise demo",
    ]:
        assert allowed in lower
    for forbidden in [
        "enterprise-ready",
        "sox compliant",
        "soc 2 certified",
        "iso certified",
        "big 4 approved",
        "blackline replacement",
        "floqast replacement",
        "workiva replacement",
        "audit opinion",
        "legal signature",
        "non-repudiation",
        "guaranteed compliance",
        "production saas",
        "direct erp connector suite",
        "real customer traction",
        "proven roi",
    ]:
        assert forbidden in lower


def test_website_launch_docs_index_and_readme_links_exist() -> None:
    docs_index = _read(Path("docs/index.md"))
    readme = _read(Path("README.md"))
    for link in DOCS_INDEX_LINKS:
        assert f"]({link})" in docs_index
    assert "](docs/website/github-launch-post.md)" in readme
    assert "](docs/website/claim-boundary-guide.md)" in readme
