"""Public diagnostic writer refuses raw leakage without financial rewrites."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_browser_diagnostic_redaction import PRIVATE_MONEY, PRIVATE_SOURCE, workspace_report

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location("owned_browser_diagnostic_writer", ROOT / ".github/scripts/verify_erp_expansion_browser.py")
assert specification is not None and specification.loader is not None
writer = importlib.util.module_from_spec(specification)
specification.loader.exec_module(writer)
TOKEN = "synthetic-session-a17-private"
CSRF = "synthetic-csrf-b29-private"
PASSWORD = "dummy-pass"


def original_oracle_publication_input(tmp_path: Path) -> tuple[Path, Path, bytes, dict[str, Any]]:
    private, output = tmp_path / "private", tmp_path / "public"
    source = private / "original-browser-download-verification"
    source.mkdir(parents=True)
    output.mkdir()
    raw = b'{"minor":9000000000000000000,"currency":"KWD"}\n'
    (source / "1-I.json").write_bytes(raw)
    (source / "1-IO.json").write_bytes(raw)
    command = b'{"argv":["python","-I"]}'
    (source / "1-I.command.json").write_bytes(command)
    proof = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    verified = {"artifacts": [{"normal": {"path": "1-I.json", **proof}, "optimized": {"path": "1-IO.json", **proof}}],
        "retained_execution_artifacts": [{"path": "1-I.command.json", "bytes": len(command), "sha256": hashlib.sha256(command).hexdigest()}]}
    (source / "custody.json").write_bytes(writer.original_verification_json_bytes(verified))
    return private, output, raw, verified


def test_original_oracle_publication_preserves_exact_financial_bytes(tmp_path: Path) -> None:
    private, output, raw, verified = original_oracle_publication_input(tmp_path)
    source = private / "original-browser-download-verification"
    result = writer.publish_original_oracle_custody(private, output, verified)
    assert result["financial_bytes_transformed"] is False
    assert result["verified_against_original_custody"] is True
    assert (output / "original-browser-download-verification/1-I.json").read_bytes() == raw
    assert (source / "1-I.json").read_bytes() == raw


def test_original_oracle_publication_rejects_unclassified_private_member_before_copy(tmp_path: Path) -> None:
    private, output = tmp_path / "private", tmp_path / "public"
    source = private / "original-browser-download-verification"
    source.mkdir(parents=True)
    output.mkdir()
    (source / "trace.zip").write_bytes(b"private network container")
    with pytest.raises(ValueError, match="unexpected member"):
        writer.publish_original_oracle_custody(private, output, {})
    assert not (output / "original-browser-download-verification").exists()


@pytest.mark.parametrize("name", ["1-I.command.json", "1-I.json", "custody.json"])
def test_original_oracle_publication_refuses_late_drift_from_successful_verification(tmp_path: Path, name: str) -> None:
    private, output, _, verified = original_oracle_publication_input(tmp_path)
    (private / "original-browser-download-verification" / name).write_bytes(b'{"altered":true}')
    with pytest.raises(ValueError, match="differs from the successful verification"):
        writer.publish_original_oracle_custody(private, output, verified)
    assert not (output / "original-browser-download-verification").exists()


def test_original_oracle_publication_quarantines_earlier_original_drift_during_later_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private, output, _, verified = original_oracle_publication_input(tmp_path)
    copy = writer.shutil.copyfileobj
    source = private / "original-browser-download-verification"
    def late_drift(reader: Any, destination: Any, *, length: int) -> None:
        copy(reader, destination, length=length)
        if Path(reader.name).name == "custody.json":
            (source / "1-I.command.json").write_bytes(b'{"altered":true}')
    monkeypatch.setattr(writer.shutil, "copyfileobj", late_drift)
    with pytest.raises(ValueError, match="changed before completed publication"):
        writer.publish_original_oracle_custody(private, output, verified)
    assert not (output / "original-browser-download-verification").exists()
    refused = list(private.glob("refused-original-oracle-publication-*"))
    assert len(refused) == 1 and (refused[0] / "1-I.command.json").is_file()


def inputs(tmp_path: Path, *, unexpected: int = 0) -> tuple[Path, Path, dict[str, bytes], dict[str, Any]]:
    output = tmp_path / "enterprise-browser-finance"
    output.mkdir()
    private = writer.private_diagnostics_directory(output)
    stats = {"expected": 1, "skipped": 0, "unexpected": unexpected, "flaky": 0, "duration": 1250.125}
    source = {"stats": stats, "suites": [{"title": "Native amount9000000000000000000", "error": {
        "message": 'GET https://localhost:54443/api/v1/native timeout status408\nCookie: __Host-session=' + TOKEN
            + '\nX-ReconForge-CSRF: ' + CSRF + '\ntrace original-stack.ts:72',
        "headers": [{"name": "Proxy-Authorization", "value": PASSWORD}],
        "status": 408, "latency_ms": 15000, "exact_minor": 9000000000000000000}}]}
    raw = {"browser.log": ("status408 GET /api/v1/native trace.ts:72\nCookie: " + TOKEN
        + "\nX-CSRF-token: " + CSRF + "\npassword=" + PASSWORD).encode(),
        "playwright.json": json.dumps(source, ensure_ascii=False, indent=2).encode(),
        "playwright-artifacts/native-cycle/error-context.md": ("# Source9000000000000000000\nSet-Cookie: "
            + TOKEN + "\nAuthorization: Bearer " + CSRF + "\nstack page.ts:34").encode()}
    for name, content in raw.items():
        path = private / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return output, private, raw, stats


def outside_artifacts(output: Path) -> dict[str, bytes]:
    untouched = {"financial-original.json": b'{"minor":9000000000000000000,"currency":"KWD"}\n',
        "independent-oracle.json": b'{"passed":true,"source_sha256":"trusted"}',
        "original.sql": b"SELECT original_amount FROM original_native_source;\n",
        "playwright-artifacts/native-cycle/screenshot.png": bytes(range(256)),
        "https-runtime.log": b"ordinary runtime status200\n", "migration.log": b"actual head143\n"}
    for name, raw in untouched.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return untouched


def test_actual_transfer_original_attachment_names_preserve_exact_bytes(tmp_path: Path) -> None:
    output, private, _, _ = inputs(tmp_path)
    names = ("inventory-transfer-browser-wire.json", "inventory-transfer-ar-mobile-read-boundary.json",
        "inventory-transfer-IT1-S-" + "A" * 32 + "-evidence.json",
        "inventory-transfer-IT1-S-" + "B" * 32 + "-evidence.json")
    originals = {}
    for name in names:
        path = private / "playwright-artifacts" / name
        raw = b'{"exact_minor":9000000000000000000,"currency":"KWD"}\r\n'
        path.write_bytes(raw)
        originals[name] = raw
    receipt = writer.publish_browser_diagnostics(output, private, [TOKEN, CSRF, PASSWORD])
    assert receipt["status"] == "published" and receipt["financial_artifacts_sanitized"] is False
    for name, raw in originals.items():
        assert (private / "playwright-artifacts" / name).read_bytes() == raw
        assert (output / "playwright-artifacts" / name).read_bytes() == raw
    for name in ("inventory-transfer-arbitrary-evidence.json", "inventory-transfer-IT1-S-short-evidence.json",
                 "inventory-transfer-IT1-S-" + "G" * 32 + "-evidence.json", "inventory-transfer-network.json"):
        assert writer._unchanged_original_artifact_name(Path(name)) is False


def assert_untouched(output: Path, originals: dict[str, bytes]) -> None:
    assert {name: (output / name).read_bytes() for name in originals} == originals


@pytest.mark.parametrize("unexpected", [0, 1])
def test_complete_private_originals_public_derivatives_exact_custody_and_unchanged_browser_stats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], unexpected: int,
) -> None:
    output, private, raw, stats = inputs(tmp_path, unexpected=unexpected)
    untouched = outside_artifacts(output)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "published" and len(result["artifacts"]) == 3
    assert result["financial_artifacts_sanitized"] is False
    assert private.parent == output.parent / (output.name + "-private-diagnostics")
    assert not private.is_relative_to(output)
    helper = ROOT / "tests/browser_diagnostic_redaction.py"
    assert result["sanitizer"]["source_sha256"] == hashlib.sha256(helper.read_bytes()).hexdigest()
    assert result["sanitizer"]["source_bytes"] == helper.stat().st_size
    assert writer.__file__ is not None
    assert result["writer"]["source_sha256"] == hashlib.sha256(Path(writer.__file__).read_bytes()).hexdigest()
    for receipt in result["artifacts"]:
        name = receipt["original_relative_path"]
        original = private / name
        assert original.read_bytes() == raw[name]
        derived = (output / name).read_bytes()
        assert receipt["original_bytes"] == len(raw[name]) and receipt["original_sha256"] == hashlib.sha256(raw[name]).hexdigest()
        assert receipt["derived_bytes"] == len(derived) and receipt["derived_sha256"] == hashlib.sha256(derived).hexdigest()
        assert all(secret.encode() not in derived for secret in (TOKEN, CSRF, PASSWORD))
    parsed = json.loads((output / "playwright.json").read_bytes())
    assert parsed["stats"] == stats
    assert parsed["suites"][0]["error"]["exact_minor"] == 9000000000000000000
    assert parsed["suites"][0]["error"]["latency_ms"] == 15000
    assert "https://localhost:54443/api/v1/native" in parsed["suites"][0]["error"]["message"]
    assert "trace original-stack.ts:72" in parsed["suites"][0]["error"]["message"]
    if unexpected:
        with pytest.raises(RuntimeError, match="unexpected"):
            writer.require_browser_acceptance(parsed["stats"])
    else:
        writer.require_browser_acceptance(parsed["stats"])
    public_receipt = (output / result["public_custody_file"]).read_bytes()
    assert json.loads(public_receipt) == result
    assert all(secret.encode() not in public_receipt for secret in (TOKEN, CSRF, PASSWORD))
    assert_untouched(output, untouched)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


@pytest.mark.parametrize("attack", ["invalid_json", "duplicate", "nonfinite", "utf8", "private_key", "private_path", "helper_exception"])
def test_any_invalid_diagnostic_quarantines_all_raw_members_before_any_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], attack: str,
) -> None:
    output, private, raw, stats = inputs(tmp_path)
    untouched = outside_artifacts(output)
    if attack in {"invalid_json", "duplicate", "nonfinite", "private_key"}:
        raw["playwright.json"] = {"invalid_json": b'{"Cookie":"' + TOKEN.encode() + b'"',
            "duplicate": b'{"stats":{},"stats":{},"suites":[]}',
            "nonfinite": b'{"stats":{"duration":NaN},"suites":[]}',
            "private_key": json.dumps({"stats": {}, "suites": [], PASSWORD: TOKEN}).encode()}[attack]
        (private / "playwright.json").write_bytes(raw["playwright.json"])
    if attack == "utf8":
        raw["browser.log"] += b"\xff"
        (private / "browser.log").write_bytes(raw["browser.log"])
    if attack == "private_path":
        source = private / "playwright-artifacts/native-cycle/error-context.md"
        target = private / ("playwright-artifacts/" + PASSWORD + "/error-context.md")
        target.parent.mkdir()
        source.rename(target)
    if attack == "helper_exception":
        def refuse(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("Cookie: " + TOKEN + " password=" + PASSWORD)
        monkeypatch.setattr(writer.diagnostic_redaction, "derive_browser_diagnostic", refuse)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "quarantined" and result["artifacts"] == []
    assert writer._public_diagnostic_paths(output) == []
    assert (private / "browser.log").read_bytes() == raw["browser.log"]
    assert (private / "playwright.json").read_bytes() == raw["playwright.json"]
    assert all(secret.encode() not in (output / result["public_custody_file"]).read_bytes() for secret in (TOKEN, CSRF, PASSWORD))
    assert_untouched(output, untouched)
    assert stats == {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 0, "duration": 1250.125}
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_existing_public_raw_is_moved_before_replacement_and_new_private_run_never_overwrites_prior_originals(tmp_path: Path) -> None:
    output, private, raw, _ = inputs(tmp_path)
    old = b"Cookie: prior-synthetic-secret\n"
    (output / "browser.log").write_bytes(old)
    old_context = output / "playwright-artifacts/previous-case/error-context.md"
    old_context.parent.mkdir(parents=True)
    old_context.write_bytes(old)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "published"
    assert (private / "public-originals/browser.log").read_bytes() == old
    assert (private / "public-originals/playwright-artifacts/previous-case/error-context.md").read_bytes() == old
    assert (private / "browser.log").read_bytes() == raw["browser.log"]
    second = writer.private_diagnostics_directory(output)
    assert second != private and second.parent == private.parent
    assert (private / "browser.log").read_bytes() == raw["browser.log"]


def test_private_financial_oracle_sql_and_screenshot_attachments_are_mirrored_as_exact_original_bytes(tmp_path: Path) -> None:
    output, private, _, _ = inputs(tmp_path)
    originals = {"cashflow-original.json": b'{"minor":9000000000000000000,"rounding":"ROUND_HALF_UP"}\n',
        "native-financial-snapshot-oracle-a17.json": b'{"source_sha256":"original","passed":true}\n',
        "original.sql": b"SELECT original_amount;\n", "screenshot.png": bytes(range(256))}
    for name, raw in originals.items():
        (private / "playwright-artifacts/native-cycle" / name).write_bytes(raw)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "published" and len(result["unchanged_browser_artifacts"]) == len(originals)
    for receipt in result["unchanged_browser_artifacts"]:
        name = receipt["relative_path"]
        original, public = private / name, output / name
        assert original.read_bytes() == public.read_bytes() == originals[public.name]
        assert receipt["original"] == receipt["public_copy"] == {"bytes": len(originals[public.name]),
            "sha256": hashlib.sha256(originals[public.name]).hexdigest()}
        assert receipt["content_transform"] is False


def test_a_different_existing_financial_original_is_never_overwritten_by_a_new_attachment(tmp_path: Path) -> None:
    output, private, _, _ = inputs(tmp_path)
    source = private / "playwright-artifacts/native-cycle/cashflow-original.json"
    source.write_bytes(b'{"minor":9000000000000000000}')
    existing = output / "playwright-artifacts/native-cycle/cashflow-original.json"
    existing.parent.mkdir(parents=True)
    original = b'{"minor":1}'
    existing.write_bytes(original)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "quarantined" and writer._public_diagnostic_paths(output) == []
    assert existing.read_bytes() == original and source.read_bytes() == b'{"minor":9000000000000000000}'


@pytest.mark.parametrize("filename", ["trace.zip", "source.har", "trace.network", "trace.json", "network.json"])
def test_raw_trace_and_network_containers_remain_private_with_hash_only_custody(tmp_path: Path, filename: str) -> None:
    output, private, _, stats = inputs(tmp_path)
    raw = b"Cookie: " + TOKEN.encode() + b"\nX-ReconForge-CSRF: " + CSRF.encode()
    source = private / "playwright-artifacts/native-cycle" / filename
    source.write_bytes(raw)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "published" and source.read_bytes() == raw
    assert not (output / "playwright-artifacts/native-cycle" / filename).exists()
    assert result["private_browser_artifacts"] == [{"artifact_index": 0,
        "kind": "private-browser-diagnostic-container", "original": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
        "published": False}]
    assert json.loads((output / "playwright.json").read_bytes())["stats"] == stats
    assert all(secret.encode() not in (output / result["public_custody_file"]).read_bytes() for secret in (TOKEN, CSRF, PASSWORD))


@pytest.mark.parametrize("filename", ["network-capture.json", "unclassified.txt", "unknown.bin"])
def test_unclassified_attachment_refuses_all_publication_without_modifying_originals(tmp_path: Path, filename: str) -> None:
    output, private, originals, _ = inputs(tmp_path)
    untouched = outside_artifacts(output)
    raw = b"Authorization: Bearer " + TOKEN.encode()
    source = private / "playwright-artifacts/native-cycle" / filename
    source.write_bytes(raw)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "quarantined" and writer._public_diagnostic_paths(output) == []
    assert source.read_bytes() == raw and not (output / "playwright-artifacts/native-cycle" / filename).exists()
    assert all((private / name).read_bytes() == content for name, content in originals.items())
    assert_untouched(output, untouched)


def test_old_public_trace_is_quarantined_before_any_current_diagnostic_publication(tmp_path: Path) -> None:
    output, private, originals, _ = inputs(tmp_path)
    old = output / "playwright-artifacts/old-case/trace.zip"
    old.parent.mkdir(parents=True)
    raw = b"Cookie: " + TOKEN.encode()
    old.write_bytes(raw)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "quarantined" and writer._public_diagnostic_paths(output) == []
    assert (private / "public-originals/playwright-artifacts/old-case/trace.zip").read_bytes() == raw
    assert all((private / name).read_bytes() == content for name, content in originals.items())


@pytest.mark.parametrize("failure", ["move_raw", "publish_derived", "concurrent_raw"])
def test_writer_io_or_publication_race_fails_closed_with_every_original_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    output, private, raw, _ = inputs(tmp_path)
    untouched = outside_artifacts(output)
    if failure == "move_raw":
        legacy = output / "playwright-artifacts/previous-case/error-context.md"
        legacy.parent.mkdir()
        legacy.write_bytes(b"Cookie: " + TOKEN.encode())
    rename = Path.rename
    def fail(path: Path, target: Path) -> Path:
        if failure == "move_raw" and path.name == "error-context.md" and path.is_relative_to(output):
            raise OSError(TOKEN)
        if failure == "publish_derived" and path.is_relative_to(private / "derived-public") and path.name == "playwright.json":
            raise OSError(TOKEN)
        return rename(path, target)
    monkeypatch.setattr(Path, "rename", fail)
    if failure == "concurrent_raw":
        derive = writer.diagnostic_redaction.derive_browser_diagnostic
        def insert(*args: Any, **kwargs: Any) -> Any:
            (output / "browser.log").write_bytes(b"Cookie: " + TOKEN.encode())
            return derive(*args, **kwargs)
        monkeypatch.setattr(writer.diagnostic_redaction, "derive_browser_diagnostic", insert)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "quarantined" and writer._public_diagnostic_paths(output) == []
    assert (private / "browser.log").read_bytes() == raw["browser.log"]
    assert (private / "playwright.json").read_bytes() == raw["playwright.json"]
    retained = private / "quarantined-public-output" if failure == "move_raw" else output
    assert_untouched(retained, untouched)


def test_browser_process_raw_bytes_and_timeout_are_private_without_exception_value_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "enterprise-browser-process"
    output.mkdir()
    private = writer.private_diagnostics_directory(output)
    stdout, stderr = b"Cookie: " + TOKEN.encode() + b"\n", b"X-ReconForge-CSRF: " + CSRF.encode()
    monkeypatch.setattr(writer.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout, stderr))
    result = writer.run_browser_process(["synthetic-browser"], environment={}, private=private)
    assert result.returncode == 1 and (private / "browser.log").read_bytes() == stdout + stderr
    assert not (output / "browser.log").exists()
    timed = writer.private_diagnostics_directory(output)
    def timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(args[0], 600, output=stdout, stderr=stderr)
    monkeypatch.setattr(writer.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out") as error:
        writer.run_browser_process(["synthetic-browser"], environment={}, private=timed)
    assert TOKEN not in str(error.value) and CSRF not in str(error.value)
    assert (timed / "browser.log").read_bytes() == stdout + stderr
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


@pytest.mark.parametrize("mode", ["passed", "browser_failed", "native_exception"])
def test_mocked_common_runner_keeps_raw_report_private_stats_exact_and_public_summary_value_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str,
) -> None:
    """Writer orchestration only: no Docker, database, browser or HTTP execution."""
    output, web = tmp_path / "enterprise-browser", tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("Synthetic writer fixture", encoding="utf8")
    monkeypatch.setattr(writer.sys, "argv", ["synthetic-runner", "--output", str(output), "--web-root", str(web)])
    monkeypatch.setattr(writer, "source_digest", lambda *args: "original-source-digest")
    monkeypatch.setattr(writer, "built_web_digest", lambda *args: "original-web-digest")
    monkeypatch.setattr(writer, "tracked_status", lambda *args: "")
    monkeypatch.setattr(writer.subprocess, "check_output", lambda *args, **kwargs: "a" * 40)
    runtime = SimpleNamespace(tenant="synthetic", password=PASSWORD)
    monkeypatch.setattr(writer, "seed_expansion_browser", lambda *args: runtime)
    def verify(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if mode == "native_exception":
            raise RuntimeError("Cookie: " + TOKEN + "\nX-CSRF-token: " + CSRF + "\npassword=" + PASSWORD)
        return {"synthetic_writer_fixture": True}
    monkeypatch.setattr(writer, "verify_expansion_cycles", verify)
    class Connection:
        def __enter__(self) -> Connection:
            return self
        def __exit__(self, *args: Any) -> None:
            pass
        def execute(self, query: Any, *args: Any) -> Any:
            value = (False, False) if "rolsuper" in str(query) else ("0143",)
            return SimpleNamespace(fetchone=lambda: value)
    monkeypatch.setattr(writer.psycopg, "connect", lambda *args, **kwargs: Connection())
    class Server:
        returncode: int | None = None
        def poll(self) -> int | None:
            return self.returncode
        def terminate(self) -> None:
            self.returncode = 0
        def wait(self, *args: Any, **kwargs: Any) -> int:
            return 0
    monkeypatch.setattr(writer.subprocess, "Popen", lambda *args, **kwargs: Server())
    class Response:
        status = 200
        def __enter__(self) -> Response:
            return self
        def __exit__(self, *args: Any) -> None:
            pass
    monkeypatch.setattr(writer.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    stats = {"expected": 1, "skipped": 0, "unexpected": int(mode == "browser_failed"), "flaky": 0, "duration": 345.125}
    cid = "b" * 64
    observed_report: list[Path] = []
    def process(argv: list[str], **options: Any) -> Any:
        if "playwright" in argv:
            environment = options["env"]
            report_path = Path(environment["RECONFORGE_ERP_BROWSER_REPORT"])
            assert not report_path.is_relative_to(output)
            observed_report.append(report_path)
            raw = {"stats": stats, "suites": [{"error": "Cookie: " + TOKEN + "\nAuthorization: " + CSRF
                + "\npassword=" + PASSWORD + "\n" + environment["RECONFORGE_GFO_APP_DSN"]}]}
            report_path.write_text(json.dumps(raw), encoding="utf8")
            context = Path(environment["RECONFORGE_ERP_BROWSER_ARTIFACTS"]) / "case/error-context.md"
            assert not context.is_relative_to(output)
            context.parent.mkdir(parents=True)
            context.write_text("Cookie: " + TOKEN, encoding="utf8")
            (context.parent / "cashflow-original.json").write_bytes(b'{"minor":9000000000000000000}')
            return subprocess.CompletedProcess(argv, int(mode == "browser_failed"), b"Cookie: " + TOKEN.encode(), b"X-CSRF-token: " + CSRF.encode())
        stdout = cid if "run" in argv or "inspect" in argv else "127.0.0.1:55555" if "port" in argv else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")
    monkeypatch.setattr(writer.subprocess, "run", process)
    assert writer.main() == (0 if mode == "passed" else 1)
    report = json.loads((output / "report.json").read_bytes())
    assert report["browser_counts"] == stats and report["owned_container_removed"] is True
    assert report["browser_diagnostics"]["status"] == "published"
    public = (output / "report.json").read_bytes() + (output / "browser.log").read_bytes() + (output / "playwright.json").read_bytes()
    assert all(secret.encode() not in public for secret in (TOKEN, CSRF, PASSWORD))
    assert json.loads((output / "playwright.json").read_bytes())["stats"] == stats
    assert (output / "playwright-artifacts/case/cashflow-original.json").read_bytes() == b'{"minor":9000000000000000000}'
    assert TOKEN in observed_report[0].read_text(encoding="utf8")
    if mode == "native_exception":
        assert TOKEN in (observed_report[0].parent / "runner-error.txt").read_text(encoding="utf8")
    captured = capsys.readouterr()
    assert all(secret not in captured.out + captured.err for secret in (TOKEN, CSRF, PASSWORD))


def workspace_inputs(tmp_path: Path) -> tuple[Path, Path, dict[str, Path], dict[str, bytes]]:
    output, private, _, _ = inputs(tmp_path)
    paths, originals, attachments = {}, {}, []
    for locale in ("en", "ar"):
        case = f"workspace-recovery-cycles--synthetic-{locale}-customer-returns-chromium"
        source = private / "playwright-artifacts" / case / f"workspace-recovery-{locale}-original-native-boundary.json"
        source.parent.mkdir()
        raw = json.dumps(workspace_report("v2", locale), ensure_ascii=False).encode()
        source.write_bytes(raw)
        copied = source.parent / "attachments" / f"workspace-recovery-{locale}-original-native-boundary-json-{'a' * 40}.json"
        copied.parent.mkdir()
        copied.write_bytes(raw)
        paths[locale], paths[locale + "-copy"] = source, copied
        originals[locale] = raw
        attachments.append({"name": source.name, "contentType": "application/json", "path": str(copied)})
    reporter = json.loads((private / "playwright.json").read_bytes())
    reporter["suites"][0]["attachments"] = attachments
    (private / "playwright.json").write_text(json.dumps(reporter), encoding="utf8")
    return output, private, paths, originals


def test_workspace_writer_publishes_only_finite_projections_and_preserves_both_private_originals(tmp_path: Path) -> None:
    output, private, paths, originals = workspace_inputs(tmp_path)
    untouched = outside_artifacts(output)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "published" and len(result["workspace_recovery_projections"]) == 2
    assert len(result["private_browser_artifacts"]) == 4
    for locale in ("en", "ar"):
        assert paths[locale].read_bytes() == paths[locale + "-copy"].read_bytes() == originals[locale]
        derived = json.loads((output / f"workspace-recovery/{locale}.json").read_bytes())
        assert derived["locale"] == locale and derived["recovery_verified"] is derived["responsive_verified"] is True
        assert derived["financial_originals_equal"] is True and derived["private_financial_originals_published"] is False
        assert derived["original_sha256"] == hashlib.sha256(originals[locale]).hexdigest()
        assert not (output / paths[locale].relative_to(private)).exists()
        assert not (output / paths[locale + "-copy"].relative_to(private)).exists()
    public = b"".join(path.read_bytes() for path in output.rglob("*") if path.is_file() and path.name not in untouched)
    assert all(value.encode() not in public for value in (PRIVATE_SOURCE, PRIVATE_MONEY, str(private), PASSWORD))
    assert writer._unchanged_original_artifact_name(paths["en"]) is False
    assert_untouched(output, untouched)


@pytest.mark.parametrize("attack", ["malformed", "duplicate_locale", "wrong_copy", "unclassified_copy", "body_only", "extra_attachment_field"])
def test_workspace_writer_refuses_invalid_private_origins_before_any_projection_publication(tmp_path: Path, attack: str) -> None:
    output, private, paths, _ = workspace_inputs(tmp_path)
    untouched = outside_artifacts(output)
    if attack == "malformed":
        paths["en"].write_bytes(b'{"financial-private":true}')
        paths["en-copy"].write_bytes(paths["en"].read_bytes())
    elif attack == "duplicate_locale":
        other = private / "playwright-artifacts/workspace-recovery-cycles--duplicate-customer-returns-chromium" / paths["en"].name
        other.parent.mkdir()
        other.write_bytes(paths["en"].read_bytes())
    elif attack == "wrong_copy":
        paths["en-copy"].write_bytes(paths["ar"].read_bytes())
    elif attack == "unclassified_copy":
        paths["en-copy"].with_name("workspace-recovery-en-original-native-boundary-random.json").write_bytes(paths["en"].read_bytes())
    else:
        report = json.loads((private / "playwright.json").read_bytes())
        attached = report["suites"][0]["attachments"][0]
        if attack == "body_only":
            attached.pop("path")
            attached["body"] = "c3ludGhldGljLXByaXZhdGU="
        else:
            attached["sourceMoney"] = PRIVATE_MONEY
        (private / "playwright.json").write_text(json.dumps(report), encoding="utf8")
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "quarantined" and result["workspace_recovery_projections"] == []
    assert writer._public_diagnostic_paths(output) == []
    assert paths["en"].is_file() and paths["en-copy"].is_file()
    assert_untouched(output, untouched)


@pytest.mark.parametrize("target", ["en", "en-copy"])
def test_workspace_writer_quarantines_partial_projections_when_original_changes_during_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
    output, private, paths, _ = workspace_inputs(tmp_path)
    untouched = outside_artifacts(output)
    rename = Path.rename
    def late_drift(path: Path, destination: Path) -> Path:
        result = rename(path, destination)
        if destination == output / "workspace-recovery/ar.json":
            paths[target].write_bytes(b'{"deliberate-original-drift":true}')
        return result
    monkeypatch.setattr(Path, "rename", late_drift)
    result = writer.publish_browser_diagnostics(output, private, [PASSWORD])
    assert result["status"] == "quarantined" and writer._public_diagnostic_paths(output) == []
    assert result["workspace_recovery_projections"] == []
    assert paths[target].read_bytes() == b'{"deliberate-original-drift":true}'
    assert_untouched(output, untouched)
