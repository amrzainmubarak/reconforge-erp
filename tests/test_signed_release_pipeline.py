from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import zipfile
from collections import Counter
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "build_release_manifest.py"
NORMALIZE_SCRIPT = ROOT / ".github" / "scripts" / "normalize_sdist.py"
FREEZE_SCRIPT = ROOT / ".github" / "scripts" / "check_publish_freeze.py"
SCHEMA = json.loads((ROOT / "docs" / "schemas" / "release_manifest.schema.json").read_text(encoding="utf-8"))
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
VERSION = "0.7.0"
REVISION = "a" * 40
IMAGE_DIGEST = "b" * 64
SOURCE_DATE_EPOCH = 1_700_000_000


def _add_tar_file(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o644
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def _add_tar_directory(archive: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.mtime = 0
    archive.addfile(info)


def _candidate_files(directory: Path, *, wheel_version: str = VERSION, unsafe_source: bool = False) -> None:
    directory.mkdir()
    source_name = f"reconforge-erp-{VERSION}-source.tar.gz"
    source_member = "../pyproject.toml" if unsafe_source else f"reconforge-erp-{VERSION}/pyproject.toml"
    with tarfile.open(directory / source_name, "w:gz") as archive:
        _add_tar_directory(archive, f"reconforge-erp-{VERSION}")
        _add_tar_file(archive, source_member, b"[project]\nname='reconforge-erp'\n")

    wheel_name = f"reconforge_erp-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(directory / wheel_name, "w") as archive:
        archive.writestr(
            f"reconforge_erp-{VERSION}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: reconforge-erp\nVersion: {wheel_version}\n",
        )

    sdist_name = f"reconforge_erp-{VERSION}.tar.gz"
    with tarfile.open(directory / sdist_name, "w:gz") as archive:
        _add_tar_directory(archive, f"reconforge_erp-{VERSION}")
        _add_tar_file(
            archive,
            f"reconforge_erp-{VERSION}/PKG-INFO",
            f"Metadata-Version: 2.4\nName: reconforge-erp\nVersion: {VERSION}\n".encode(),
        )


def _ensure_test_project(project_root: Path) -> None:
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(
            '[project]\nname = "reconforge-erp"\nversion = "0.7.0"\n',
            encoding="utf-8",
        )


def _run_manifest(
    directory: Path,
    *,
    tag: str = f"v{VERSION}",
    image_digest: str = IMAGE_DIGEST,
    source_date_epoch: int = SOURCE_DATE_EPOCH,
) -> subprocess.CompletedProcess[str]:
    project_root = directory.parent
    _ensure_test_project(project_root)
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project-root",
            str(project_root),
            "--release-dir",
            str(directory),
            "--tag",
            tag,
            "--source-revision",
            REVISION,
            "--source-date-epoch",
            str(source_date_epoch),
            "--image-subject",
            f"ghcr.io/amrzainmubarak/reconforge-erp@sha256:{image_digest}",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_release_manifest_is_closed_deterministic_and_checksum_bound(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    _candidate_files(release_dir)

    first = _run_manifest(release_dir)
    assert first.returncode == 0, first.stderr
    manifest_path = release_dir / "release-manifest.v1.json"
    checksums_path = release_dir / "SHA256SUMS"
    first_manifest_bytes = manifest_path.read_bytes()
    first_checksum_bytes = checksums_path.read_bytes()
    payload = json.loads(first_manifest_bytes)
    jsonschema.Draft202012Validator(SCHEMA).validate(payload)

    assert [artifact["id"] for artifact in payload["artifacts"]] == [
        "source-archive",
        "python-wheel",
        "python-sdist",
        "container-image",
    ]
    assert payload["release"] == {
        "signed_annotated_tag_required": True,
        "source_repository": "https://github.com/amrzainmubarak/reconforge-erp",
        "source_revision": REVISION,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "tag": "v0.7.0",
        "version": "0.7.0",
    }
    assert payload["builder"]["assessment"] == "UNEVALUATED"

    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        digest, filename = line.split("  ", 1)
        assert hashlib.sha256((release_dir / filename).read_bytes()).hexdigest() == digest

    second = _run_manifest(release_dir)
    assert second.returncode == 0, second.stderr
    assert manifest_path.read_bytes() == first_manifest_bytes
    assert checksums_path.read_bytes() == first_checksum_bytes


@pytest.mark.parametrize(
    ("tag", "image_digest", "wheel_version", "expected"),
    [
        ("v0.7.1", IMAGE_DIGEST, VERSION, "tag must exactly match"),
        (f"v{VERSION}", "not-a-digest", VERSION, "image subject must contain"),
        (f"v{VERSION}", IMAGE_DIGEST, "0.7.1", "wheel metadata does not match"),
    ],
)
def test_release_manifest_rejects_identity_drift(
    tmp_path: Path,
    tag: str,
    image_digest: str,
    wheel_version: str,
    expected: str,
) -> None:
    release_dir = tmp_path / "release"
    _candidate_files(release_dir, wheel_version=wheel_version)
    result = _run_manifest(release_dir, tag=tag, image_digest=image_digest)
    assert result.returncode != 0
    assert expected in result.stderr
    assert not (release_dir / "release-manifest.v1.json").exists()


def test_release_manifest_rejects_archive_traversal(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    _candidate_files(release_dir, unsafe_source=True)
    result = _run_manifest(release_dir)
    assert result.returncode != 0
    assert "unsafe or unexpected path" in result.stderr


@pytest.mark.parametrize("source_date_epoch", [-1, 1 << 32])
def test_release_manifest_rejects_source_epoch_outside_gzip_range(
    tmp_path: Path,
    source_date_epoch: int,
) -> None:
    release_dir = tmp_path / "release"
    _candidate_files(release_dir)
    result = _run_manifest(release_dir, source_date_epoch=source_date_epoch)
    assert result.returncode != 0
    assert "SOURCE_DATE_EPOCH is outside the gzip timestamp range" in result.stderr


def _normalizer_fixture(path: Path, *, member_mtime: int, unsafe_kind: str | None = None) -> None:
    path.parent.mkdir(parents=True)
    root = f"reconforge_erp-{VERSION}"
    with tarfile.open(path, "w:gz") as archive:
        directory = tarfile.TarInfo(root)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        directory.mtime = member_mtime
        directory.uid = 123
        directory.gid = 456
        directory.uname = "builder"
        directory.gname = "builder"
        archive.addfile(directory)
        _add_tar_file(
            archive,
            f"{root}/PKG-INFO",
            f"Metadata-Version: 2.4\nName: reconforge-erp\nVersion: {VERSION}\n".encode(),
        )
        payload = b"deterministic-content\n"
        file_info = tarfile.TarInfo(f"{root}/payload.txt")
        file_info.size = len(payload)
        file_info.mode = 0o644
        file_info.mtime = member_mtime
        file_info.uid = 123
        file_info.gid = 456
        file_info.uname = "builder"
        file_info.gname = "builder"
        archive.addfile(file_info, io.BytesIO(payload))
        if unsafe_kind == "traversal":
            _add_tar_file(archive, f"{root}/../escape.txt", b"escape")
        elif unsafe_kind == "link":
            link = tarfile.TarInfo(f"{root}/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "payload.txt"
            archive.addfile(link)


def _run_normalizer(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(NORMALIZE_SCRIPT),
            "--path",
            str(path),
            "--source-date-epoch",
            str(SOURCE_DATE_EPOCH),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_sdist_normalizer_produces_identical_safe_archives(tmp_path: Path) -> None:
    left = tmp_path / "left" / f"reconforge_erp-{VERSION}.tar.gz"
    right = tmp_path / "right" / f"reconforge_erp-{VERSION}.tar.gz"
    _normalizer_fixture(left, member_mtime=100)
    _normalizer_fixture(right, member_mtime=200)

    for path in [left, right]:
        result = _run_normalizer(path)
        assert result.returncode == 0, result.stderr
        assert int.from_bytes(path.read_bytes()[4:8], "little") == SOURCE_DATE_EPOCH
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
        assert [member.name for member in members] == sorted(member.name for member in members)
        assert all(member.mtime == SOURCE_DATE_EPOCH for member in members)
        assert all((member.uid, member.gid, member.uname, member.gname) == (0, 0, "", "") for member in members)

    assert left.read_bytes() == right.read_bytes()


@pytest.mark.parametrize("unsafe_kind", ["traversal", "link"])
def test_sdist_normalizer_rejects_unsafe_members_without_overwriting(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    path = tmp_path / unsafe_kind / f"reconforge_erp-{VERSION}.tar.gz"
    _normalizer_fixture(path, member_mtime=100, unsafe_kind=unsafe_kind)
    original = path.read_bytes()
    result = _run_normalizer(path)
    assert result.returncode != 0
    assert path.read_bytes() == original


def test_release_workflow_is_tag_only_least_privilege_and_full_sha_pinned() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.load(raw, Loader=yaml.BaseLoader)
    assert workflow["on"] == {"push": {"tags": ["v*"]}}
    assert workflow["permissions"] == {}
    job = workflow["jobs"]["build-attest-verify"]
    assert job["environment"] == "release-candidate"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
        "packages": "write",
    }

    action_refs = re.findall(r"^\s*uses:\s*([^\s#]+)", raw, re.MULTILINE)
    assert Counter(action_refs) == Counter(
        {
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1": 1,
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97": 1,
            "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020": 1,
            "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9": 1,
            "docker/login-action@abd2ef45e78c5afb21d64d4ca52ee8550d9572c7": 1,
            "docker/setup-buildx-action@bb05f3f5519dd87d3ba754cc423b652a5edd6d2c": 1,
            "docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a": 1,
            "actions/attest@f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6": 6,
            "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a": 1,
        }
    )
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_refs)
    assert raw.count("uses: actions/attest@f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6") == 6
    assert "contents: write" not in raw
    assert "workflow_dispatch" not in raw
    assert "pull_request" not in raw
    assert "gh release create" not in raw
    assert "twine" not in raw.lower()


def test_release_workflow_fails_closed_on_source_attestation_and_runner_identity() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    for required in [
        "git status --porcelain=v1 --untracked-files=all",
        "git merge-base --is-ancestor",
        ".verification.verified",
        ".verification.reason",
        "python -m pip install --disable-pip-version-check --only-binary=:all:",
        "--require-hashes -r .github/release-build-requirements.txt",
        "SOURCE_DATE_EPOCH",
        "python .github/scripts/normalize_sdist.py",
        '--source-date-epoch "${SOURCE_DATE_EPOCH}"',
        "--signer-workflow",
        "--signer-digest",
        "--source-ref",
        "--source-digest",
        "--deny-self-hosted-runners",
        "--bundle release/files-provenance.sigstore.json",
        "--bundle release/image-provenance.sigstore.json",
        "sha256sum --check SHA256SUMS",
        "sha256sum --check SBOM_SHA256SUMS",
        "No GitHub Release or PyPI publication was performed.",
    ]:
        assert required in raw
    assert raw.count("gh attestation verify") == 6
    assert "provenance: false" in raw
    assert "sbom: false" in raw
    assert "candidate-${{ github.sha }}" in raw


def test_release_workflow_enforces_the_active_publication_freeze() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "check_publish_freeze.py" in raw
    assert "--decision-id D-485" in raw


def _run_freeze_check(decisions: Path, decision_id: str = "D-485") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(FREEZE_SCRIPT),
            "--decisions",
            str(decisions),
            "--decision-id",
            decision_id,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_publication_freeze_guard_is_fail_closed_until_explicitly_closed(tmp_path: Path) -> None:
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text("### D-485: defer publication\n- **Decision**: hold\n", encoding="utf-8")
    active = _run_freeze_check(decisions)
    assert active.returncode == 1
    assert "Publication freeze is active" in active.stdout

    decisions.write_text(
        "### D-485: defer publication\n- **Status**: closed\n- **Decision**: hold\n",
        encoding="utf-8",
    )
    closed = _run_freeze_check(decisions)
    assert closed.returncode == 0
    assert "explicitly closed" in closed.stdout


def test_publication_freeze_guard_ignores_missing_decision(tmp_path: Path) -> None:
    result = _run_freeze_check(tmp_path / "missing.md")
    assert result.returncode == 1
    assert "Publication freeze is active" in result.stdout


def test_publication_freeze_guard_is_fail_closed_without_decisions_file(tmp_path: Path) -> None:
    result = _run_freeze_check(tmp_path / "does-not-exist.md")
    assert result.returncode == 1
    assert "Publication freeze is active" in result.stdout


def test_release_build_tools_are_exact_and_hash_locked() -> None:
    requirements = (ROOT / ".github" / "release-build-requirements.txt").read_text(encoding="utf-8")
    requirement_lines = [line for line in requirements.splitlines() if line and not line.startswith("#")]
    assert len(requirement_lines) == 6
    assert all(
        re.fullmatch(r'[a-z-]+==[0-9.]+(?: ; os_name == "nt")? --hash=sha256:[0-9a-f]{64}', line)
        for line in requirement_lines
    )
    assert {line.split("==", 1)[0] for line in requirement_lines} == {
        "build",
        "colorama",
        "packaging",
        "pyproject-hooks",
        "setuptools",
        "wheel",
    }


def test_signed_release_runbook_keeps_publication_and_claims_human_gated() -> None:
    text = (ROOT / "docs" / "maintainers" / "signed-release-candidates.md").read_text(encoding="utf-8").lower()
    for phrase in [
        "does not publish a github release or pypi package",
        "release-candidate` environment with required reviewers",
        "enable github immutable releases",
        "gh release verify",
        "gh release verify-asset",
        "both slsa tracks remain unevaluated",
        "do not overwrite or delete evidence",
    ]:
        assert phrase in text
