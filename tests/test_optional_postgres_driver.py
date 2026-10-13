"""Exercise Community startup with the enterprise-only driver unavailable."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_community_doctor_runs_when_optional_postgres_driver_is_unavailable(tmp_path: Path) -> None:
    program = r"""
import importlib.abc
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
class UnavailablePostgres(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'psycopg' or fullname.startswith('psycopg.'):
            raise ModuleNotFoundError('Optional PostgreSQL driver deliberately unavailable', name=fullname)
        return None
sys.meta_path.insert(0, UnavailablePostgres())
from typer.testing import CliRunner
from reconforge.cli import app
result = CliRunner().invoke(app, ['doctor', '--input', str(root/'examples/sample_data'),
    '--config', str(root/'config/reconforge.yml'), '--output', sys.argv[2]])
if result.exit_code != 0:
    raise AssertionError((result.output, type(result.exception).__name__))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(ROOT), str(tmp_path / "doctor")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
