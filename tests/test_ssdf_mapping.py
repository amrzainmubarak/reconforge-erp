from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "docs" / "security" / "nist-ssdf-1.1-mapping.v1.yaml"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "ssdf_mapping.schema.json"
ARCHITECTURE_PATH = ROOT / "docs" / "security" / "security-architecture.v2.yaml"
READABLE_PATH = ROOT / "docs" / "security" / "nist-ssdf-mapping.md"

OFFICIAL_GROUPS = {
    "PO": "Prepare the Organization",
    "PS": "Protect the Software",
    "PW": "Produce Well-Secured Software",
    "RV": "Respond to Vulnerabilities",
}

OFFICIAL_PRACTICE_TASKS = {
    "PO.1": ("Define Security Requirements for Software Development", ("PO.1.1", "PO.1.2", "PO.1.3")),
    "PO.2": ("Implement Roles and Responsibilities", ("PO.2.1", "PO.2.2", "PO.2.3")),
    "PO.3": ("Implement Supporting Toolchains", ("PO.3.1", "PO.3.2", "PO.3.3")),
    "PO.4": ("Define and Use Criteria for Software Security Checks", ("PO.4.1", "PO.4.2")),
    "PO.5": ("Implement and Maintain Secure Environments for Software Development", ("PO.5.1", "PO.5.2")),
    "PS.1": ("Protect All Forms of Code from Unauthorized Access and Tampering", ("PS.1.1",)),
    "PS.2": ("Provide a Mechanism for Verifying Software Release Integrity", ("PS.2.1",)),
    "PS.3": ("Archive and Protect Each Software Release", ("PS.3.1", "PS.3.2")),
    "PW.1": (
        "Design Software to Meet Security Requirements and Mitigate Security Risks",
        ("PW.1.1", "PW.1.2", "PW.1.3"),
    ),
    "PW.2": (
        "Review the Software Design to Verify Compliance with Security Requirements and Risk Information",
        ("PW.2.1",),
    ),
    "PW.4": (
        "Reuse Existing Well-Secured Software When Feasible",
        ("PW.4.1", "PW.4.2", "PW.4.4"),
    ),
    "PW.5": ("Create Source Code by Adhering to Secure Coding Practices", ("PW.5.1",)),
    "PW.6": (
        "Configure Compilation Interpreter and Build Processes for Executable Security",
        ("PW.6.1", "PW.6.2"),
    ),
    "PW.7": ("Review or Analyze Human-Readable Code", ("PW.7.1", "PW.7.2")),
    "PW.8": (
        "Test Executable Code for Vulnerabilities and Security Requirements",
        ("PW.8.1", "PW.8.2"),
    ),
    "PW.9": ("Configure Software to Have Secure Settings by Default", ("PW.9.1", "PW.9.2")),
    "RV.1": (
        "Identify and Confirm Vulnerabilities on an Ongoing Basis",
        ("RV.1.1", "RV.1.2", "RV.1.3"),
    ),
    "RV.2": ("Assess Prioritize and Remediate Vulnerabilities", ("RV.2.1", "RV.2.2")),
    "RV.3": (
        "Analyze Vulnerabilities to Identify Their Root Causes",
        ("RV.3.1", "RV.3.2", "RV.3.3", "RV.3.4"),
    ),
}


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _practices(payload: dict[str, object]) -> list[dict[str, object]]:
    return [practice for group in payload["groups"] for practice in group["practices"]]


def _tasks(payload: dict[str, object]) -> list[dict[str, object]]:
    return [task for practice in _practices(payload) for task in practice["tasks"]]


def test_ssdf_mapping_matches_closed_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(_load_yaml(MAPPING_PATH))


def test_ssdf_source_pin_distinguishes_final_draft_and_ai_profile() -> None:
    standard = _load_yaml(MAPPING_PATH)["standard"]
    assert standard == {
        "publication": "NIST SP 800-218",
        "ssdf_version": "1.1",
        "publication_status": "final",
        "published": "2022-02-03",
        "verified_at": "2026-07-25",
        "official_publication_url": "https://csrc.nist.gov/pubs/sp/800/218/final",
        "doi_url": "https://doi.org/10.6028/NIST.SP.800-218",
        "pdf": {
            "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-218.pdf",
            "sha256": "617746e553a9e2da49bfbd4eef0dfc3094758a39b869314e4173ac36605cde22",
            "bytes": 739891,
        },
        "official_table": {
            "url": "https://csrc.nist.gov/files/pubs/sp/800/218/final/docs/nist.sp.800-218.ssdf-table.xlsx",
            "sha256": "f5729c4c6c792cbf6cfbea74eee7cc84c579b2109006fe3cbfa8934eb460bd55",
            "bytes": 50039,
        },
        "official_counts": {"groups": 4, "practices": 19, "tasks": 42},
        "source_note": (
            "Identifiers, group/practice names, and counts were reviewed from the official "
            "NIST PDF and Excel table in memory; the source files and task prose are not "
            "copied into this repository."
        ),
        "excluded_draft": {
            "publication": "NIST SP 800-218 Rev. 1",
            "ssdf_version": "1.2",
            "status": "initial-public-draft",
            "published": "2025-12-17",
            "url": "https://csrc.nist.gov/pubs/sp/800/218/r1/ipd",
            "reason": (
                "NIST lists version 1.2 as an Initial Public Draft, so it is monitored but "
                "excluded from this final-publication mapping."
            ),
        },
        "supplemental_profile": {
            "publication": "NIST SP 800-218A",
            "status": "final",
            "published": "2024-07-26",
            "url": "https://csrc.nist.gov/pubs/sp/800/218/a/final",
            "applicability": (
                "A separate profile assessment is required before promoting any generative "
                "AI model or model-backed system capability; it is not silently treated as "
                "covered or not applicable by this core SSDF 1.1 mapping."
            ),
        },
    }


def test_ssdf_all_groups_practices_tasks_and_status_totals_are_exact() -> None:
    payload = _load_yaml(MAPPING_PATH)
    groups = {group["group_id"]: group["group_name"] for group in payload["groups"]}
    practices = {
        practice["practice_id"]: (
            practice["practice_name"],
            tuple(task["task_id"] for task in practice["tasks"]),
        )
        for practice in _practices(payload)
    }
    tasks = _tasks(payload)
    statuses = Counter(task["status"] for task in tasks)

    assert groups == OFFICIAL_GROUPS
    assert practices == OFFICIAL_PRACTICE_TASKS
    assert len(tasks) == len({task["task_id"] for task in tasks}) == 42
    assert statuses == {"partial": 28, "planned": 14}
    assert payload["summary"] == {
        "official_group_count": 4,
        "official_practice_count": 19,
        "official_task_count": 42,
        "status_counts": {
            "implemented_bounded": 0,
            "partial": 28,
            "planned": 14,
            "not_applicable": 0,
        },
    }


def test_ssdf_owners_evidence_gaps_and_review_cadence_are_bounded() -> None:
    payload = _load_yaml(MAPPING_PATH)
    architecture = _load_yaml(ARCHITECTURE_PATH)
    owners = {owner["id"] for owner in architecture["control_owners"]}

    assert payload["review"]["owner"] in owners
    assert payload["review"]["cadence_days"] == 90
    assert date.fromisoformat(payload["review"]["next_review_due"]) > date.fromisoformat(payload["last_reviewed"])
    for practice in _practices(payload):
        assert practice["owner"] in owners
    for task in _tasks(payload):
        assert task["owner"] in owners
        for evidence_path in [*task["evidence"], *task["test_evidence"]]:
            assert (ROOT / evidence_path).is_file(), evidence_path
        if task["status"] in {"implemented_bounded", "partial"}:
            assert task["evidence"]
            assert task["test_evidence"]
        else:
            assert task["evidence"] == []
            assert task["test_evidence"] == []
        assert task["gap_or_limitation"]
        assert task["next_action"]

    boundary = payload["claim_boundary"].lower()
    assert "not an organizational ssdf conformance assessment" in boundary
    assert "no task is promoted to implemented-bounded" in boundary


def test_readable_ssdf_mapping_discloses_complete_scope_and_boundaries() -> None:
    readable = READABLE_PATH.read_text(encoding="utf-8")
    for group_id, group_name in OFFICIAL_GROUPS.items():
        assert f"`{group_id}`" in readable
        assert group_name in readable
    for practice_id, (practice_name, _) in OFFICIAL_PRACTICE_TASKS.items():
        assert f"`{practice_id}`" in readable
        assert practice_name in readable
    assert "42" in readable
    assert "28" in readable
    assert "14" in readable
    assert "not an ssdf conformance" in readable.lower()
    assert "initial public draft" in readable
    assert "SP 800-218A" in readable
