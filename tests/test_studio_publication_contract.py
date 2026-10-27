"""The real Studio browser clients must survive source publication."""

import ast
import runpy
from pathlib import Path

from setuptools._distutils.filelist import FileList

from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / ".github/scripts/verify_global_integrity_archive.py"
ENTRYPOINTS = {
    "apps/web/live/studio-navigation.ts",
    "apps/web/e2e/release-product-harness.html",
    "apps/web/e2e/release-product-harness.tsx",
    "apps/web/e2e/studio-shell.manifest.mjs",
}


def test_source_export_preserves_real_browser_entrypoints() -> None:
    files = FileList()
    files.set_allfiles([
        str(path.relative_to(ROOT))
        for folder in ("apps/web/e2e", "apps/web/live")
        for path in (ROOT / folder).rglob("*") if path.is_file()
    ])
    for line in (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        if line.startswith(("include apps/web/e2e/", "recursive-include apps/web/e2e ", "recursive-include apps/web/live ")):
            files.process_template_line(line)
    published = {Path(path).as_posix() for path in files.files}
    assert "apps/web/e2e/studio-shell.playwright.config.ts" in published
    assert published >= ENTRYPOINTS


def test_publication_verifier_requires_studio_support_files() -> None:
    namespace = runpy.run_path(str(VERIFIER), run_name="studio_publication_contract")
    assert set(namespace.get("STUDIO_REQUIRED", ())) >= ENTRYPOINTS


def test_publication_migration_defaults_match_the_current_official_chain() -> None:
    defaults = {}
    for node in ast.walk(ast.parse(VERIFIER.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument" and node.args and isinstance(node.args[0], ast.Constant)
        ):
            for keyword in node.keywords:
                if keyword.arg == "default" and node.args[0].value in {"--migration-count", "--migration-head"}:
                    defaults[node.args[0].value] = ast.literal_eval(keyword.value)
    assert defaults == {
        "--migration-count": len(POSTGRES_MIGRATION_REVISIONS),
        "--migration-head": POSTGRES_MIGRATION_REVISIONS[-1],
    }
