"""Inspect already-built publication artifacts; never build or execute benchmarks."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

HELPERS = (
    "commercial_collections_browser", "erp_landed_cost_browser", "stock_commerce_browser_seed",
    "fixed_assets_browser_seed", "erp_procurement_enterprise_browser", "enterprise_financial_snapshot_browser",
    "customer_returns_browser", "erp_procurement_commitments_browser",
    "operational_fx_tax_browser_seed", "erp_supplier_returns_browser",
)
PREFIX20_SHA = "3f1ecffac62b7cc3cbea41264f2a61b7948d9875c87dd32f7eddf7f51238be41"
INDEX_PATH = "docs/execution/benchmarks/INDEX.v1.json"
GOLDEN = {100: "46669102", 1000: "493671004"}
FX_EVIDENCE = "docs/execution/wave4-evidence/fx-1e73267e"
FX_MANIFEST_SHA = "3ac5b0bf960862abcd5b11183de059a6a4df61f3b6fac3a7feab59cf633cf58a"
FX_RETAINED_SHA = {
    "cycle-report.json": "594b41ada0420a647b1c0b99aa083c0d631635276e7a7aa133352706c65ae027",
    "proof-manifest.json": FX_MANIFEST_SHA,
    "oracle-normal.json": "cd5e6657b80f2dfa656599bb54be369fedea15dd60703ead17c73dcb44735a98",
    "oracle-optimized.json": "3e2be012104525d438b09059efb12f4a32c1626572cac0bed92c00783d129456",
}


def require(value: object, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=root, text=True, timeout=30).strip()


def source_digest(root: Path, tracked: set[str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(tracked):
        digest.update(name.encode("utf-8"))
        digest.update(hashlib.sha256((root / name).read_bytes()).digest())
    return digest.hexdigest()


def retained(packet: dict[str, object]) -> dict[str, object]:
    policy = packet["original_report_serialization"]
    require(isinstance(policy, dict), "Missing original serialization metadata")
    require(policy["encoding"] == "utf-8" and policy["final_newline"] is True, "Unsupported raw serialization")
    report = packet["measurement"]
    require(isinstance(report, dict), "Original report must be an object")
    text = json.dumps(report, indent=policy["indent"], ensure_ascii=policy["ensure_ascii"], allow_nan=False) + "\n"
    require(policy["line_endings"] in {"LF", "CRLF"}, "Unsupported raw line endings")
    if policy["line_endings"] == "CRLF":
        text = text.replace("\n", "\r\n")
    require(sha(text.encode("utf-8")) == packet["original_report_sha256"], "Retained report is not byte-exact")
    return report


def check_pair(extracted: Path, names: tuple[str, str]) -> dict[str, object]:
    reports = []
    outputs = []
    for name in names:
        packet = json.loads((extracted / name).read_text(encoding="utf-8"))
        report = retained(packet)
        require(report["status"] == "passed" and report["source_unchanged"] is True, "Pair report did not pass unchanged")
        require(report["source_commit"] == report["source_commit_after"], "Pair source commit changed")
        require(report["source_sha256"] == report["source_sha256_after"] == packet["source_sha256"], "Pair source digest changed")
        require(report["owned_container_removed"] is True and report["runtime_role_flags"] == [False, False], "Pair runtime/cleanup evidence invalid")
        require(report["profile"] == "native-three-human-cash-equity-v1" and report["seed"] == "enterprise-native-v1", "Wrong paired workload")
        require(report["counts"] == [100, 1000] and report["workers"] == 4 and report["repetitions"] == 3, "Wrong paired admission")
        posting = report["posting"]
        require(posting["requested_cycles"] == posting["admitted_cycles"] == posting["completed_cycles"] == 1000, "Incomplete posting tier")
        require(posting["error_count"] == posting["not_admitted_cycles"] == 0 and posting["failed_cycles"] == [], "Posting failure concealed")
        require(posting["completed_indices"] == list(range(1000)) and len(posting["ordered_effect_ids"]) == len(set(posting["ordered_effect_ids"])) == 1000, "Posting identities incomplete")
        vectors = posting["raw_cycle_latency_seconds"]
        require(len(vectors) == 1000 and all(math.isfinite(v) and v >= 0 for v in vectors), "Raw posting vector incomplete")
        require(posting["expected"] == {k: GOLDEN[1000] for k in ("debit_minor", "credit_minor", "cash_minor", "equity_minor")}, "Independent posting money oracle failed")
        require(len(report["verified_reads"]) == 2, "Read tiers incomplete")
        request_count = 0
        for read in report["verified_reads"]:
            count = read["count"]
            require(count in GOLDEN and read["status"] == "passed", "Unexpected read tier")
            require(read["expected"] == {k: GOLDEN[count] for k in ("debit_minor", "credit_minor", "cash_minor", "equity_minor")}, "Independent read money oracle failed")
            require(read["cache_policy"] == "both warmed; alternating modes", "Read cache/order policy changed")
            require(set(read["samples"]) == {"per_effect_baseline", "bounded_batch"}, "Read modes changed")
            for mode, samples in read["samples"].items():
                require([sample["repetition"] for sample in samples] == [0, 1, 2], "Read repetitions incomplete")
                for sample in samples:
                    raw = sample["raw_request_latency_seconds"]
                    require(len(raw) == (count if mode == "per_effect_baseline" else count // 100), "Raw read vector incomplete")
                    require(all(math.isfinite(v) and v >= 0 for v in raw), "Invalid raw read timing")
                    require(sample["status"] == "complete" and sample["error_count"] == 0 and sample["effects"] == count, "Read observation failed")
                    require(sample["debit_minor"] == sample["credit_minor"] == GOLDEN[count], "Observed independent read money mismatch")
                    require(sample["effects_digest"] == read["financial_effects_digest"], "Read changed native financial evidence")
                    request_count += len(raw)
            if count == 1000:
                require(read["financial_effects_digest"] == packet["financial_effects_digest"], "Wrapper financial digest differs")
        require(request_count == 3333, "Timed read requests incomplete")
        sampling = report["resource_sampling"]
        require(sampling["status"] == "complete" and sampling["errors"] == [] and sampling["thread_still_running"] is False, "Resource sampler incomplete")
        require(sampling["interval_seconds"] == 10 and bool(sampling["raw_samples"]), "Resource samples absent")
        outputs.append({"artifact": name, "source_commit": report["source_commit"], "source_sha256": report["source_sha256"],
                        "original_report_sha256": packet["original_report_sha256"], "posting_observations": len(vectors),
                        "timed_read_observations": request_count, "resource_samples": len(sampling["raw_samples"])})
        reports.append(report)
    workload_fields = ("schema_version", "profile", "seed", "counts", "workers", "repetitions", "max_seconds", "image", "telemetry_policy")
    for field in workload_fields:
        require(reports[0][field] == reports[1][field], "Paired workload mismatch: " + field)
    environment_fields = ("python", "platform", "logical_cpus", "processor", "architecture", "docker_version", "docker_engine_resources", "postgres_version", "postgres_configuration")
    differences = [field for field in environment_fields if reports[0][field] != reports[1][field]]
    return {"raw_reports": outputs, "workload_fields_equal": list(workload_fields), "environment_fields_different": differences,
            "claim_boundary": "Artifact integrity and bounded independent money correctness; environment differences require explicit comparison disclosure."}


def check_migrations(extracted: Path, count: int, head: str) -> dict[str, object]:
    revisions = {}
    for path in sorted((extracted / "alembic/versions").glob("*.py")):
        assignments = {}
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        assignments[target.id] = ast.literal_eval(node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in {"revision", "down_revision"}:
                assignments[node.target.id] = ast.literal_eval(node.value)
        require(set(assignments) == {"revision", "down_revision"}, "Migration declaration missing: " + path.name)
        require(assignments["revision"] not in revisions, "Duplicate migration revision")
        revisions[assignments["revision"]] = assignments["down_revision"]
    require(len(revisions) == count, "Migration file count differs")
    visited = []
    current = head
    while current is not None:
        require(current in revisions and current not in visited, "Broken or cyclic migration chain")
        visited.append(current)
        current = revisions[current]
    require(len(visited) == count and set(visited) == set(revisions), "Migration chain does not cover every revision")
    if count >= 131:
        require(visited[-125] == "0125_pg_landed_cost_cancellation", "Accepted 125-revision prefix differs")
        require(visited[:6] == ["0131_pg_fx_revaluation", "0130_pg_supplier_returns", "0129_pg_financial_read_plans",
                               "0128_pg_operational_fx_tax", "0127_pg_procurement_commitments", "0126_pg_customer_returns"],
                "Wave4 migration suffix differs")
    return {"count": count, "head": head, "oldest": visited[-1], "complete_linear_chain": True}


def isolated_json(command: list[str], root: Path) -> dict[str, object]:
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=120)
    require(result.returncode == 0, "Extracted-source verifier failed: " + result.stderr[-3000:])
    return json.loads(result.stdout)


def check_wave4_evidence(extracted: Path, output: Path) -> dict[str, object]:
    packet = json.loads((extracted / "docs/execution/WAVE4_ACCEPTANCE_2026-10-10.json").read_bytes())
    require(packet["final_acceptance"] is False, "Incremental Wave4 packet claims final acceptance")
    embedded = 0

    def check_retained(value: object) -> None:
        nonlocal embedded
        if isinstance(value, dict):
            if "original_report_serialization" in value:
                require(isinstance(value["original_report_serialization"], str), "Wave4 original report serialization differs")
                require(sha(value["original_report_serialization"].encode("utf-8")) == value["original_report_sha256"],
                        "Wave4 embedded original report bytes differ")
                embedded += 1
            for child in value.values():
                check_retained(child)
        elif isinstance(value, list):
            for child in value:
                check_retained(child)

    check_retained(packet)
    require(embedded == 44 and len(packet["retained_unsuccessful_attempts"]) == 23, "Wave4 retained report population differs")
    require(len(packet["accepted_native_owner_packets"]) == 7 and len(packet["original_fx_unique_executed_case_ids"]) == 19,
            "Wave4 source-bound native population differs")
    for native_packet in packet["accepted_native_owner_packets"].values():
        native = json.loads(native_packet["original_report_serialization"])
        counts = native_packet["independently_parsed_junit_counts"]
        require(native["accepted"] is True and native["source_unchanged"] is True and native["counts"] == counts,
                "Wave4 native acceptance/source/JUnit counts differ")
        require(type(counts["tests"]) is int and counts["tests"] > 0
                and all(type(counts[key]) is int and counts[key] == 0 for key in ("failures", "errors", "skipped")),
                "Wave4 native execution incomplete")
    browser = packet["accepted_actual_https_and_populated_restore"]
    require(set(browser) == {"customer_returns", "procurement_commitments", "fx_five_stage", "supplier_returns"},
            "Wave4 accepted actual cycle set differs")
    for retained_browser in browser.values():
        runtime = json.loads(retained_browser["original_report_serialization"])
        require(runtime["status"] == "passed" and runtime["source_unchanged"] is True
                and runtime["source_commit"] == runtime["source_commit_after"], "Wave4 accepted runtime source differs")
        require(all(runtime[key] is True for key in ("tracked_clean_before", "tracked_clean_after", "built_web_unchanged",
                                                     "owned_container_removed", "owned_https_process_stopped"))
                and runtime["role_privileges"] == [False, False]
                and all(type(flag) is bool for flag in runtime["role_privileges"]), "Wave4 runtime isolation/cleanup differs")
        require(all(type(runtime["browser_counts"][key]) is int and runtime["browser_counts"][key] == count
                    for key, count in {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 0}.items()),
                "Wave4 actual runtime outcome differs")
        require(runtime["native_restore"]["status"] == "passed" and runtime["native_restore"]["tamper_refusals"] == 3
                and runtime["persisted_effects"] == runtime["native_restore"]["verified_effects"], "Wave4 restore financial evidence differs")
    require(all(attempt["accepted"] is False for attempt in packet["retained_unsuccessful_attempts"])
            and packet["retained_interrupted_general_partition"]["accepted"] is False, "Wave4 unaccepted attempt promoted")
    evidence = extracted / FX_EVIDENCE
    for name, expected_sha in FX_RETAINED_SHA.items():
        require(sha((evidence / name).read_bytes()) == expected_sha, "Retained FX raw bytes differ: " + name)
    manifest = json.loads((evidence / "proof-manifest.json").read_bytes())
    for index, effect in enumerate(manifest["native_effects"]):
        require(sha((evidence / f"fx-proof-{index}.json").read_bytes()) == effect["file_sha256"], "FX original proof bytes differ")
    require((evidence / "fx-proof-ar-mobile.json").read_bytes() == (evidence / "fx-proof-4.json").read_bytes(),
            "FX Arabic retained final evidence differs")
    validations = {}
    for mode in ("normal", "optimized"):
        fresh = output / ("independent-fx-cycle-" + mode + ".json")
        isolated_json([sys.executable, "-I", *(["-O"] if mode == "optimized" else []),
                       str(extracted / ".github/scripts/verify_operational_fx_cycle_oracle.py"),
                       "--proof-directory", str(evidence), "--cycle-report", str(evidence / "cycle-report.json"),
                       "--proof-manifest", str(evidence / "proof-manifest.json"), "--proof-manifest-sha256", FX_MANIFEST_SHA,
                       "--report", str(fresh)], extracted)
        current = json.loads(fresh.read_bytes())
        original = json.loads((evidence / ("oracle-" + mode + ".json")).read_bytes())
        require(current["status"] == original["status"] == "passed", "Extracted FX rational oracle failed")
        for field in ("proof_manifest_sha256", "source_commit", "source_sha256", "built_web_sha256", "report_sha256", "dump_sha256",
                      "native_effects", "unique_audit_events", "unique_outbox_events", "account_balances_minor", "source_id", "invoice_id",
                      "foreign_gross_minor", "functional_gross_minor", "foreign_receipts_minor", "historical_releases_minor",
                      "realized_fx_minor", "closing_value_minor", "unrealized_difference_minor", "restored_table_count"):
            require(current[field] == original[field], "Extracted FX independent result differs: " + field)
        validations[mode] = current
    return {"embedded_original_reports": embedded, "actual_cycle_count": len(browser),
            "trusted_manifest_sha256": FX_MANIFEST_SHA, "original_raw_hashes": FX_RETAINED_SHA,
            "independent_fx_oracle": validations, "final_program_acceptance": False}


def check_imports(extracted: Path) -> dict[str, object]:
    code = """
import importlib,json,pathlib,sys
sys.dont_write_bytecode=True
root=pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0,str(root))
origins={}
for name in json.loads(sys.argv[2]):
 module=importlib.import_module('tests.'+name)
 location=pathlib.Path(module.__file__).resolve()
 assert location==root/'tests'/(name+'.py'),(name,str(location))
 origins[name]=str(location)
for name,module in tuple(sys.modules.items()):
 if (name=='reconforge' or name.startswith('reconforge.') or name=='tests' or name.startswith('tests.')) and getattr(module,'__file__',None):
  pathlib.Path(module.__file__).resolve().relative_to(root)
print(json.dumps({'helpers':origins,'all_loaded_reconforge_and_tests_modules_from_extracted_source':True}))
"""
    return isolated_json([sys.executable, "-I", "-c", code, str(extracted), json.dumps((*HELPERS, "mandatory_native_gate"))], extracted)


def inspect(args: argparse.Namespace, report: dict[str, object]) -> None:
    require(hasattr(tarfile, "data_filter"), "Safe archive inspection requires tarfile.data_filter (Python 3.11.4+)")
    root = args.root.resolve()
    source_commit = git(root, "rev-parse", "HEAD")
    require(not git(root, "status", "--porcelain", "--untracked-files=no"), "Publication source has tracked mutations")
    tracked = {name for name in git(root, "ls-files", "-z").split("\0") if name}
    source_before = source_digest(root, tracked)
    index = json.loads((root / INDEX_PATH).read_text(encoding="utf-8"))
    require(len(index["entries"]) == args.index_count, "Unexpected final benchmark entry count")
    require(sha(json.dumps(index["entries"][:20], sort_keys=True, separators=(",", ":")).encode("utf-8")) == PREFIX20_SHA, "Twenty retained index entries changed")
    pair = ("docs/execution/benchmarks/" + args.baseline_wrapper, "docs/execution/benchmarks/" + args.candidate_wrapper)
    required = {
        "LICENSE", "README.md", "MANIFEST.in", "pyproject.toml", "alembic.ini", "reconforge_migration_sql.py",
        "alembic/env.py", "alembic/script.py.mako", "tests/__init__.py", INDEX_PATH,
        "tests/mandatory_native_gate.py", "tests/test_mandatory_native_gate.py",
        "tests/test_benchmark_evidence_index.py", "tests/test_alembic_postgres.py",
        ".github/scripts/verify_benchmark_index.py", ".github/scripts/verify_commercial_collections.py",
        ".github/scripts/benchmark_enterprise_finance.py", "tests/fixtures/landed_cost_owner_0123_69951414.sql",
        ".github/scripts/verify_global_integrity_archive.py", ".github/scripts/verify_native_posting_pair.py",
        "tests/test_native_posting_pair_verifier.py",
        "tests/test_container_resource_counters.py", "tests/test_postgres_financial_read_plans.py",
        "tests/test_global_engineering_pair.py", "tests/fixtures/enterprise-warmup-20-ea83335c.json",
        "tests/test_customer_returns.py", "tests/test_customer_returns_api.py", "tests/test_postgres_customer_returns.py",
        "tests/test_procurement_commitments.py", "tests/test_postgres_procurement_commitments.py", "tests/test_postgres_procurement_commitments_api.py",
        "tests/test_operational_fx_tax.py", "tests/test_postgres_operational_fx_tax.py", "tests/test_postgres_operational_fx_tax_api.py",
        "tests/test_postgres_operational_fx_tax_migration.py", ".github/scripts/benchmark_global_engineering_pair.py",
        "tests/test_supplier_returns.py", "tests/test_postgres_supplier_returns.py", "tests/test_postgres_supplier_returns_api.py",
        "tests/test_operational_fx_revaluation.py", "tests/test_postgres_operational_fx_revaluation.py",
        "tests/test_postgres_operational_fx_revaluation_migration.py", ".github/scripts/verify_erp_expansion_browser.py",
        ".github/scripts/verify_operational_fx_cycle_oracle.py", "tests/test_operational_fx_cycle_oracle.py",
        "docs/execution/WAVE4_ACCEPTANCE_2026-10-10.json", "docs/execution/WAVE4_ACCEPTANCE_2026-10-10.md",
        "docs/execution/wave4-evidence/.gitattributes",
        *(FX_EVIDENCE + "/" + name for name in FX_RETAINED_SHA),
        *(FX_EVIDENCE + f"/fx-proof-{index}.json" for index in range(5)), FX_EVIDENCE + "/fx-proof-ar-mobile.json",
        "apps/web/src/operational-fx-tax-fixture.json", "modules/customer-returns.yaml",
        "docs/modules/procurement-commitments.yaml", "docs/modules/operational-fx-tax.yaml",
        "docs/modules/supplier-returns.yaml", "docs/operator/supplier-returns.md",
        "docs/adr/0851-original-supplier-debit-and-capitalized-receipt-return.md",
        "docs/operator/customer-returns.md", "docs/operator/procurement-commitments.md", "docs/operator/operational-fx-tax.md",
        "docs/adr/0847-original-customer-source-credits-and-partial-refunds.md",
        "docs/adr/0848-native-purchase-appropriation-closure.md", "docs/adr/0849-historical-foreign-ar-effective-tax-and-realized-fx.md",
        "docs/adr/0850-invoker-financial-read-policy-planning.md", "docs/execution/GLOBAL_CAPABILITY_COVERAGE_WAVE4_2026-10-10.md",
        "apps/web/src/fixed-asset-evidence-fixture.json", "docs/adr/0845-governed-abandonment-and-native-evidence-performance.md",
        "docs/adr/0846-retained-unreceived-landed-cost-cancellation.md", "docs/operator/commercial-collections.md",
        "docs/operator/landed-cost.md", "docs/operator/fixed-assets.md", "docs/execution/GLOBAL_ENGINEERING_BENCHMARK_2026-10-10.md",
        "docs/execution/GLOBAL_CAPABILITY_COVERAGE_2026-10-10.md", "docs/execution/GLOBAL_CAPABILITY_COVERAGE_WAVE3_2026-10-10.md",
        "docs/execution/" + args.acceptance_stem + ".json", "docs/execution/" + args.acceptance_stem + ".md",
        *("tests/" + name + ".py" for name in HELPERS), *pair,
        *(entry["artifact"] for entry in index["entries"]),
        *(name for name in tracked if (name.startswith("reconforge/") or name.startswith("alembic/versions/")) and name.endswith(".py")),
    }
    require(all((root / name).is_file() for name in required), "Final required source member is absent")
    require(all(name in tracked for name in required), "Final required source member is not committed")
    report.update(source_root=str(root), source_commit=source_commit, source_sha256_before=source_before,
                  sdist_sha256=sha(args.sdist.read_bytes()), wheel_sha256=sha(args.wheel.read_bytes()))
    with tempfile.TemporaryDirectory(prefix="reconforge-sdist-inspection-") as temporary:
        target = Path(temporary).resolve()
        require(not target.is_relative_to(root) and not root.is_relative_to(target), "Extraction must be outside publication root")
        with tarfile.open(args.sdist, "r:gz") as archive:
            files = {}
            prefixes = set()
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                require(not path.is_absolute() and ".." not in path.parts and "\\" not in member.name, "Unsafe archive member")
                require(not member.issym() and not member.islnk() and not member.isdev(), "Source archive links/devices are refused")
                require(bool(path.parts), "Empty archive member")
                prefixes.add(path.parts[0])
                if member.isfile():
                    relative = PurePosixPath(*path.parts[1:]).as_posix()
                    require(relative not in files, "Duplicate source archive member")
                    files[relative] = member
            require(len(prefixes) == 1, "Source archive must have one top-level root")
            require(required <= set(files), "Source archive misses required members: " + ", ".join(sorted(required - set(files))))
            parity = {}
            for name in sorted(tracked & set(files)):
                original = (root / name).read_bytes()
                stored = archive.extractfile(files[name]).read()
                require(stored == original, "Source archive byte mismatch: " + name)
                parity[name] = sha(stored)
            archive.extractall(target, filter="data")
        extracted = target / next(iter(prefixes))
        report["sdist"] = {"file_members": len(files), "required_members": len(required), "exact_tracked_member_hashes": parity}
        require(b"MIT License" in (extracted / "LICENSE").read_bytes() and b"Permission is hereby granted, free of charge" in (extracted / "LICENSE").read_bytes(), "MIT source license absent")
        report["migrations"] = check_migrations(extracted, args.migration_count, args.migration_head)
        report["benchmark_index"] = isolated_json([sys.executable, "-I", str(extracted / ".github/scripts/verify_benchmark_index.py"),
                "--root", str(extracted), "--index", str(extracted / INDEX_PATH)], extracted)
        require(len(report["benchmark_index"]["verified_entries"]) == args.index_count, "Extracted index count differs")
        report["paired_raw_reports"] = check_pair(extracted, pair)
        pair_proof = target / "independent-posting-pair.json"
        isolated_json([sys.executable, "-I", str(extracted / ".github/scripts/verify_native_posting_pair.py"),
                       "--root", str(extracted), "--report", str(pair_proof)], extracted)
        report["independent_posting_pair"] = json.loads(pair_proof.read_text(encoding="utf-8"))
        require(report["independent_posting_pair"]["status"] == "passed", "Extracted independent posting oracle failed")
        report["wave4_portable_evidence"] = check_wave4_evidence(extracted, target)
        report["browser_helper_imports"] = check_imports(extracted)
        report["acceptance_packet_keys"] = sorted(json.loads((extracted / "docs/execution" / (args.acceptance_stem + ".json")).read_text(encoding="utf-8")))
        with zipfile.ZipFile(args.wheel) as wheel:
            names = wheel.namelist()
            require(len(names) == len(set(names)), "Duplicate wheel member")
            wheel_parity = {}
            for name in sorted(n for n in required if n.startswith("reconforge/") and n.endswith(".py")):
                require(name in names and wheel.read(name) == (root / name).read_bytes(), "Wheel Python source mismatch: " + name)
                wheel_parity[name] = sha(wheel.read(name))
            for name in sorted(n for n in required if n.startswith("alembic/") or n in {"alembic.ini", "reconforge_migration_sql.py"}):
                hits = [n for n in names if n == name or n.endswith("/" + name)]
                require(len(hits) == 1 and wheel.read(hits[0]) == (root / name).read_bytes(), "Wheel migration asset mismatch: " + name)
                wheel_parity[name] = sha(wheel.read(hits[0]))
            licenses = [n for n in names if n.endswith(".dist-info/LICENSE") or n.endswith(".dist-info/licenses/LICENSE")]
            require(len(licenses) == 1 and wheel.read(licenses[0]) == (root / "LICENSE").read_bytes(), "Wheel MIT license mismatch")
            report["wheel"] = {"exact_source_member_hashes": wheel_parity, "license_member": licenses[0]}
    report["temporary_extraction_removed"] = not target.exists()
    require(report["temporary_extraction_removed"], "Owned extraction directory remains")
    require(git(root, "rev-parse", "HEAD") == source_commit and not git(root, "status", "--porcelain", "--untracked-files=no"), "Publication source changed during inspection")
    report["source_sha256_after"] = source_digest(root, tracked)
    require(report["source_sha256_after"] == source_before, "Publication source bytes changed during inspection")
    report.update(status="passed", source_unchanged=True, tracked_clean_before=True, tracked_clean_after=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--index-count", type=int, default=22)
    parser.add_argument("--migration-count", type=int, default=131)
    parser.add_argument("--migration-head", default="0131_pg_fx_revaluation")
    parser.add_argument("--acceptance-stem", default="GLOBAL_INTEGRITY_ACCEPTANCE_2026-10-10")
    parser.add_argument("--baseline-wrapper", default="enterprise-native-finance-wave3-baseline-806a05db-2026-10-10.json")
    parser.add_argument("--candidate-wrapper", default="enterprise-native-finance-wave3-candidate-70dffef7-2026-10-10.json")
    args = parser.parse_args()
    if args.report.exists():
        parser.error("Refuse to overwrite a retained inspection report")
    if args.report.resolve().is_relative_to(args.root.resolve()):
        ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", str(args.report.resolve())], cwd=args.root, timeout=30)
        if ignored.returncode:
            parser.error("An inspection report inside publication source must be explicitly ignored")
    report: dict[str, object] = {"schema_version": "publication-source-closure-v1", "status": "failed"}
    try:
        inspect(args, report)
    except Exception as exc:
        report.update(error_type=type(exc).__name__, error=str(exc))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(args.report.resolve()), "report_sha256": sha(args.report.read_bytes()),
                      "source_commit": report.get("source_commit"), "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
