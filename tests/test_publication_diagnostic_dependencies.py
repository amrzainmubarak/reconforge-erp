"""Source distributions must retain the real dependencies of diagnostic tests."""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publication_diagnostic_dependencies", ROOT / ".github/scripts/verify_global_integrity_archive.py"
)
assert SPEC is not None and SPEC.loader is not None
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


def extracted_helpers(target: Path) -> None:
    for relative in archive.DIAGNOSTIC_HELPERS:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)


def test_real_extracted_helpers_import_in_isolated_process_without_native_workload(tmp_path: Path) -> None:
    extracted_helpers(tmp_path)
    proof = archive.check_diagnostic_imports(tmp_path)
    assert set(proof["helpers"]) == {
        ".github/scripts/benchmark_wave5_profile_diagnostics.py", ".github/scripts/verify_wave5_large_journal.py"
    }
    assert proof["workload_executed"] is False
    assert proof["application_database_profiler_imports"] is False
    assert all(Path(item["source"]).is_relative_to(tmp_path) for item in proof["helpers"].values())


@pytest.mark.parametrize("missing", [
    ".github/scripts/benchmark_wave5_profile_diagnostics.py", ".github/scripts/verify_wave5_large_journal.py"
])
def test_archive_refuses_each_missing_diagnostic_dependency(tmp_path: Path, missing: str) -> None:
    extracted_helpers(tmp_path)
    (tmp_path / missing).unlink()
    with pytest.raises(ValueError, match="misses diagnostic test dependencies"):
        archive.check_diagnostic_imports(tmp_path)


@pytest.mark.parametrize("prefix", ["reconforge", "psycopg", "psycopg2", "psutil"])
def test_archive_refuses_helper_loading_application_database_or_profiler(tmp_path: Path, prefix: str) -> None:
    extracted_helpers(tmp_path)
    helper = tmp_path / archive.DIAGNOSTIC_HELPERS[0]
    helper.write_text("import sys\nsys.modules[" + repr(prefix + ".unapproved") + "]=object()\n", encoding="utf-8")
    with pytest.raises(ValueError, match="application/database/profiler code"):
        archive.check_diagnostic_imports(tmp_path)


def test_archive_refuses_import_time_process_workload(tmp_path: Path) -> None:
    extracted_helpers(tmp_path)
    helper = tmp_path / archive.DIAGNOSTIC_HELPERS[0]
    helper.write_text("import subprocess\nsubprocess.Popen(['this-native-workload-must-never-launch'])\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot launch processes or network workloads"):
        archive.check_diagnostic_imports(tmp_path)
