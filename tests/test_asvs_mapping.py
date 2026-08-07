from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "docs" / "security" / "asvs-5.0.0-mapping.v1.yaml"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "asvs_mapping.schema.json"
ARCHITECTURE_PATH = ROOT / "docs" / "security" / "security-architecture.v2.yaml"
READABLE_PATH = ROOT / "docs" / "security" / "asvs-mapping.md"

OFFICIAL_CHAPTERS = {
    "V1": ("Encoding and Sanitization", 30),
    "V2": ("Validation and Business Logic", 13),
    "V3": ("Web Frontend Security", 31),
    "V4": ("API and Web Service", 16),
    "V5": ("File Handling", 13),
    "V6": ("Authentication", 47),
    "V7": ("Session Management", 19),
    "V8": ("Authorization", 13),
    "V9": ("Self-contained Tokens", 7),
    "V10": ("OAuth and OIDC", 36),
    "V11": ("Cryptography", 24),
    "V12": ("Secure Communication", 12),
    "V13": ("Configuration", 21),
    "V14": ("Data Protection", 13),
    "V15": ("Secure Coding and Architecture", 21),
    "V16": ("Security Logging and Error Handling", 17),
    "V17": ("WebRTC", 12),
}

OFFICIAL_SELECTED_LEVELS = {
    "v5.0.0-1.2.4": 1,
    "v5.0.0-1.2.10": 3,
    "v5.0.0-1.5.1": 1,
    "v5.0.0-2.2.1": 1,
    "v5.0.0-2.3.3": 2,
    "v5.0.0-2.3.5": 3,
    "v5.0.0-3.2.2": 1,
    "v5.0.0-3.4.4": 2,
    "v5.0.0-3.5.1": 1,
    "v5.0.0-4.1.1": 1,
    "v5.0.0-4.1.4": 3,
    "v5.0.0-4.3.1": 2,
    "v5.0.0-4.4.1": 1,
    "v5.0.0-5.1.1": 2,
    "v5.0.0-5.2.1": 1,
    "v5.0.0-5.2.2": 1,
    "v5.0.0-5.3.2": 1,
    "v5.0.0-5.4.3": 2,
    "v5.0.0-6.1.1": 1,
    "v5.0.0-6.2.1": 1,
    "v5.0.0-6.3.1": 1,
    "v5.0.0-6.4.3": 2,
    "v5.0.0-7.2.1": 1,
    "v5.0.0-7.2.3": 1,
    "v5.0.0-7.4.1": 1,
    "v5.0.0-8.1.1": 1,
    "v5.0.0-8.2.2": 1,
    "v5.0.0-8.3.1": 1,
    "v5.0.0-9.1.1": 1,
    "v5.0.0-10.4.1": 1,
    "v5.0.0-10.5.1": 2,
    "v5.0.0-11.2.1": 2,
    "v5.0.0-11.4.2": 2,
    "v5.0.0-11.5.1": 2,
    "v5.0.0-12.1.1": 1,
    "v5.0.0-12.2.1": 1,
    "v5.0.0-12.3.2": 2,
    "v5.0.0-13.1.1": 2,
    "v5.0.0-13.3.1": 2,
    "v5.0.0-13.4.2": 2,
    "v5.0.0-14.1.1": 2,
    "v5.0.0-14.2.4": 2,
    "v5.0.0-14.3.2": 2,
    "v5.0.0-15.1.1": 1,
    "v5.0.0-15.1.2": 2,
    "v5.0.0-15.2.1": 1,
    "v5.0.0-15.4.2": 3,
    "v5.0.0-16.1.1": 2,
    "v5.0.0-16.2.1": 2,
    "v5.0.0-16.2.2": 2,
    "v5.0.0-16.2.5": 2,
    "v5.0.0-16.3.2": 2,
    "v5.0.0-16.5.1": 2,
    "v5.0.0-17.1.1": 2,
    "v5.0.0-17.2.1": 2,
}


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _mappings(payload: dict[str, object]) -> list[dict[str, object]]:
    return [mapping for chapter in payload["chapters"] for mapping in chapter["mappings"]]


def test_asvs_mapping_matches_closed_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(_load_yaml(MAPPING_PATH))


def test_asvs_source_pin_and_chapter_counts_match_reviewed_stable_release() -> None:
    payload = _load_yaml(MAPPING_PATH)
    standard = payload["standard"]
    assert standard == {
        "name": "OWASP Application Security Verification Standard",
        "version": "5.0.0",
        "release_status": "stable",
        "release_date": "2025-05-30",
        "verified_at": "2026-07-25",
        "release_tag": "v5.0.0_release",
        "release_commit": "5cf9b032440be53ce345ab3c130fda46ba1ce7a2",
        "official_project_url": "https://owasp.org/www-project-application-security-verification-standard/",
        "official_release_url": "https://github.com/OWASP/ASVS/releases/tag/v5.0.0_release",
        "official_source_url": (
            "https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0_release/5.0/docs_en/"
            "OWASP_Application_Security_Verification_Standard_5.0.0_en.csv"
        ),
        "official_source_sha256": "98c8fe911b9edb403af8ee05d3ce8201ecac2659e313b053890a62847cdcf680",
        "official_source_bytes": 105100,
        "license": "CC-BY-SA-4.0",
        "reference_format": "v<version>-<chapter>.<section>.<requirement>",
        "excluded_source": (
            "The mutable master-branch Bleeding Edge release was checked but excluded; "
            "OWASP explicitly directs production users to the stable v5.0.0 release."
        ),
    }

    observed = {
        chapter["chapter_id"]: (chapter["chapter_name"], chapter["official_requirement_count"])
        for chapter in payload["chapters"]
    }
    assert observed == OFFICIAL_CHAPTERS
    assert sum(count for _, count in observed.values()) == 345


def test_asvs_selected_ids_levels_and_summary_are_exact() -> None:
    payload = _load_yaml(MAPPING_PATH)
    mappings = _mappings(payload)
    selected = {mapping["requirement_id"]: mapping["level"] for mapping in mappings}
    counts = Counter(mapping["status"] for mapping in mappings)

    assert len(selected) == len(mappings) == 55
    assert selected == OFFICIAL_SELECTED_LEVELS
    assert payload["summary"] == {
        "official_chapter_count": 17,
        "official_requirement_count": 345,
        "mapped_requirement_count": 55,
        "unassessed_requirement_count": 290,
        "status_counts": {
            "implemented": counts["implemented"],
            "partial": counts["partial"],
            "planned": counts["planned"],
            "not_applicable": counts["not_applicable"],
        },
    }
    assert counts == {"implemented": 4, "partial": 34, "planned": 10, "not_applicable": 7}


def test_asvs_statuses_have_evidence_and_residual_boundaries() -> None:
    payload = _load_yaml(MAPPING_PATH)
    architecture = _load_yaml(ARCHITECTURE_PATH)
    owners = {owner["id"] for owner in architecture["control_owners"]}

    for mapping in _mappings(payload):
        assert mapping["owner"] in owners
        for evidence_path in [*mapping["evidence"], *mapping["test_evidence"]]:
            assert (ROOT / evidence_path).is_file(), evidence_path
        if mapping["status"] in {"implemented", "partial"}:
            assert mapping["evidence"]
            assert mapping["test_evidence"]
        else:
            assert mapping["evidence"] == []
            assert mapping["test_evidence"] == []
        if mapping["status"] == "not_applicable":
            assert "reassess" in mapping["next_action"].lower()

    boundary = payload["claim_boundary"].lower()
    assert "not a full 345-requirement assessment" in boundary
    assert "not a compliance" in boundary
    assert "not" in payload["status_definitions"]["unassessed"].lower()


def test_readable_asvs_mapping_discloses_scope_and_all_chapters() -> None:
    readable = READABLE_PATH.read_text(encoding="utf-8")
    for chapter_id, (chapter_name, _) in OFFICIAL_CHAPTERS.items():
        assert f"`{chapter_id}`" in readable
        assert chapter_name in readable
    assert "55" in readable
    assert "290" in readable
    assert "not a compliance" in readable.lower()
