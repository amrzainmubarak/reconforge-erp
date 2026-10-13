"""Synthetic adversarial diagnostics; no original credential packets are read."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.browser_diagnostic_redaction import (
    PRIVATE_HEADERS,
    REDACTED,
    derive_browser_diagnostic,
    redact_browser_text,
    redact_playwright_value,
)

SECRET = "synthetic-session-secret-123456789"
CSRF = "synthetic-csrf-secret-987654321"
PASSWORD = 'synthetic-pw-"雪"-\\-123456789'
IDENTITY = "a" * 64


@pytest.mark.parametrize("header", sorted(PRIVATE_HEADERS))
@pytest.mark.parametrize("line_break", ["\n", "\r\n", "\\n", "\\r\\n"])
def test_case_insensitive_plain_headers_real_and_json_escaped_lines_preserve_request_diagnostics(header, line_break):
    message = line_break.join([
        "route.fetch: Timeout 15000ms", "Call log:", "  - GET https://127.0.0.1:44123/api/v1/procurement-sourcing/quote",
        "  - " + header.upper() + ": __Host-session=" + SECRET + "; Max-Age=300; Secure; HttpOnly",
        "  - status: 503", "  - x-request-id: trace-31", "  - latency: 14999.75ms", "at quote.spec.ts:42:9",
    ])
    result = redact_browser_text(message)
    assert SECRET not in result and "__Host-session=" not in result
    assert result == message.replace("__Host-session=" + SECRET + "; Max-Age=300; Secure; HttpOnly", REDACTED)
    assert redact_browser_text(result) == result


@pytest.mark.parametrize("layers", range(4))
def test_embedded_json_header_maps_quoted_values_and_escaped_quotes(layers):
    message = json.dumps({"Cookie": SECRET + '; quoted="inner-secret"', "Authorization": "Bearer " + CSRF,
                          "status": 504, "endpoint": "/api/v1/report", "latency": 15000.5})
    for _ in range(layers):
        message = json.dumps(message)[1:-1]
    result = redact_browser_text(message)
    assert SECRET not in result and CSRF not in result and "inner-secret" not in result
    assert "504" in result and "/api/v1/report" in result and "15000.5" in result
    decoded = result
    for _ in range(layers):
        decoded = json.loads('"' + decoded + '"')
    parsed = json.loads(decoded)
    assert parsed == {"Cookie": REDACTED, "Authorization": REDACTED, "status": 504,
                      "endpoint": "/api/v1/report", "latency": 15000.5}


@pytest.mark.parametrize("layers", range(4))
@pytest.mark.parametrize("ending", ["\\", "\\\\", '\\"'])
def test_complete_opaque_quoted_header_including_trailing_escaped_characters_is_removed(layers, ending):
    message = json.dumps({"Proxy-Authorization": SECRET + ending, "status": 502})
    for _ in range(layers):
        message = json.dumps(message)[1:-1]
    result = redact_browser_text(message)
    for _ in range(layers):
        result = json.loads('"' + result + '"')
    assert json.loads(result) == {"Proxy-Authorization": REDACTED, "status": 502}


@pytest.mark.parametrize("prefix", ["", "Running one required test\n"])
def test_browser_stdout_json_last_header_line_preserves_outer_status_trace_and_numeric_stats(prefix):
    message = {"error": {"message": "route.fetch timeout\n - Cookie: " + SECRET,
                         "stack": "quote.spec.ts:42:9", "endpoint": "/api/v1/quote"},
               "status": 503, "stats": {"duration": 15000.75, "unexpected": 1, "flaky": 0}}
    result = redact_browser_text(prefix + json.dumps(message))
    parsed = json.loads(result[len(prefix):])
    assert SECRET not in result and parsed["error"]["message"].endswith(REDACTED)
    assert parsed["status"] == message["status"] and parsed["stats"] == message["stats"]
    assert parsed["error"]["stack"] == message["error"]["stack"] and parsed["error"]["endpoint"] == message["error"]["endpoint"]


def test_playwright_report_all_string_values_header_records_and_known_escaped_credentials_are_redacted():
    report = {"stats": {"expected": 0, "unexpected": 1, "flaky": 0, "skipped": 0, "duration": 15102.75},
        "suites": [{"specs": [{"tests": [{"results": [{"status": "failed", "duration": 15000,
        "error": {"message": "route.fetch: Timeout 15000ms\n  - cOoKiE: __Host-session=" + SECRET
            + "\n  - x-Reconforge-Csrf: " + CSRF + "\n  - status: 503\nat source.spec.ts:42:9",
            "stack": "source.spec.ts:42:9\nTrace: trace-1234\nKnown password: " + PASSWORD},
        "attachments": [{"name": "Authorization", "value": "Bearer " + SECRET},
                        {"name": "public trace", "value": "trace-1234"}],
        "headers": {"SET-COOKIE": ["__Host-session=" + SECRET, "secondary=" + CSRF], "X-CSRF-TOKEN": CSRF,
                    "x-trace-id": "trace-1234"}}]}]}]}],
        "errors": [json.dumps({"password": PASSWORD})], "config": {"workers": 1}}
    original = json.dumps(report, ensure_ascii=False).encode()
    derived = derive_browser_diagnostic("playwright.json", original, sanitizer_source_sha256=IDENTITY,
                                        known_private_values=(SECRET, CSRF, PASSWORD))
    parsed = json.loads(derived.content)
    assert parsed["stats"] == report["stats"] and parsed["config"] == report["config"]
    result = parsed["suites"][0]["specs"][0]["tests"][0]["results"][0]
    assert result["duration"] == 15000 and result["status"] == "failed"
    assert "status: 503" in result["error"]["message"] and "source.spec.ts:42:9" in result["error"]["stack"]
    assert result["attachments"] == [{"name": "Authorization", "value": REDACTED}, {"name": "public trace", "value": "trace-1234"}]
    assert result["headers"] == {"SET-COOKIE": [REDACTED, REDACTED], "X-CSRF-TOKEN": REDACTED, "x-trace-id": "trace-1234"}
    assert json.loads(original) == report
    for private in (SECRET, CSRF, PASSWORD, json.dumps(PASSWORD)[1:-1]):
        assert private not in derived.content.decode()
    assert derived.receipt["original_sha256"] == hashlib.sha256(original).hexdigest()
    assert derived.receipt["derived_sha256"] == hashlib.sha256(derived.content).hexdigest()
    assert derived.receipt["sanitizer"]["source_sha256"] == IDENTITY
    assert SECRET not in json.dumps(derived.receipt) and CSRF not in json.dumps(derived.receipt)


def test_only_browser_diagnostics_admitted_and_financial_sql_oracle_screenshot_bytes_untouched(tmp_path):
    files = {
        "browser.log": ("route.fetch timeout\nCookie: " + SECRET + "\nstatus: 503\ncount: 7").encode(),
        "playwright.json": json.dumps({"suites": [], "stats": {"unexpected": 1, "duration": 15000}, "errors": ["CSRF=" + CSRF]}).encode(),
        "playwright-artifacts/source-case/error-context.md": ("# Error\n- X-CSRF-token: " + CSRF + "\nGET /api/v1/report\n").encode(),
        "cashflow-original.json": b'{"cash_minor":4500000000000000000,"cookie":"financial-source-literal"}',
        "group-diagnostic-original.json": b'{"native_minor":-4500000000000000000,"reporting_minor":202}',
        "original.sql": b"INSERT INTO source VALUES (10001,3334,3334,3333);",
        "oracle.json": b'{"passed":true,"original_sha256":"abc","checks":121}',
        "playwright-artifacts/source-case/test-failed-1.png": b"\x89PNG\r\n\x1a\nsynthetic-original-pixels",
    }
    before = {}
    for name, raw in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        before[name] = hashlib.sha256(raw).hexdigest()
    outputs = []
    for name, raw in files.items():
        if name in {"browser.log", "playwright.json", "playwright-artifacts/source-case/error-context.md"}:
            outputs.append(derive_browser_diagnostic(name, raw, sanitizer_source_sha256=IDENTITY, known_private_values=(SECRET, CSRF)))
        else:
            with pytest.raises(ValueError, match="allowlist"):
                derive_browser_diagnostic(name, raw, sanitizer_source_sha256=IDENTITY, known_private_values=(SECRET, CSRF))
    assert all(SECRET not in output.content.decode() and CSRF not in output.content.decode() for output in outputs)
    assert {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in files} == before
    assert json.loads((tmp_path / "cashflow-original.json").read_bytes())["cash_minor"] == 4_500_000_000_000_000_000


@pytest.mark.parametrize("name", ["../browser.log", "/browser.log", "C:/browser.log", "x/../browser.log",
                                  "playwright-artifacts/../x/error-context.md", "playwright-artifacts\\x\\error-context.md"])
def test_path_escape_never_selects_diagnostic_artifact(name):
    with pytest.raises(ValueError):
        derive_browser_diagnostic(name, b"Cookie: " + SECRET.encode(), sanitizer_source_sha256=IDENTITY)


@pytest.mark.parametrize("original", [b'{"stats":{},"suites":[],"stats":{"unexpected":0}}',
                                      b'{"stats":{"duration":NaN},"suites":[]}', b'{"financial_minor":10001}', b"\xff"])
def test_invalid_or_non_playwright_json_refuses_without_private_value_in_error(original):
    with pytest.raises(ValueError) as refused:
        derive_browser_diagnostic("playwright.json", original, sanitizer_source_sha256=IDENTITY, known_private_values=(SECRET,))
    assert SECRET not in str(refused.value)


def test_known_private_field_name_and_marker_collision_refuse_publication_without_leaking_values():
    with pytest.raises(ValueError) as refused:
        redact_playwright_value({SECRET: "private-key"}, (SECRET,))
    assert SECRET not in str(refused.value)
    with pytest.raises(ValueError):
        redact_browser_text("private", ("redacted",))
    with pytest.raises(ValueError) as refused_path:
        derive_browser_diagnostic("playwright-artifacts/" + SECRET + "/error-context.md", b"safe",
                                  sanitizer_source_sha256=IDENTITY, known_private_values=(SECRET,))
    assert SECRET not in str(refused_path.value)


def test_endpoints_stack_trace_and_public_header_values_are_retained():
    public = "GET https://127.0.0.1:44123/api/v1/Cookie:trace\n at /src/Set-Cookie:42:9\n - x-trace-id: trace-314\nstatus:503 latency:15000 count:7"
    assert redact_browser_text(public) == public
    assert redact_playwright_value({"status": 503, "latency": 15000.25, "count": 7, "endpoint": public}) == {
        "status": 503, "latency": 15000.25, "count": 7, "endpoint": public}


def test_helper_is_stdlib_pure_and_receipt_never_echoes_original_values():
    import ast

    import tests.browser_diagnostic_redaction as helper

    source = Path(helper.__file__).read_bytes()
    modules = {node.module.split(".")[0] for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom) and node.module}
    modules.update(alias.name.split(".")[0] for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import) for alias in node.names)
    assert modules <= {"__future__", "hashlib", "json", "re", "collections", "dataclasses", "pathlib", "typing"}
    original = ("Cookie: " + SECRET).encode()
    derived = derive_browser_diagnostic("browser.log", original, sanitizer_source_sha256=hashlib.sha256(source).hexdigest())
    assert SECRET not in json.dumps(derived.receipt)
    assert derived.receipt["original_mutated"] is False and derived.receipt["financial_artifacts_sanitized"] is False


@pytest.mark.parametrize("layers", range(7))
@pytest.mark.parametrize("kind", ["browser.log", "playwright.json", "playwright-artifacts/ansi-case/error-context.md"])
def test_ansi_prefixed_and_reescaped_real_playwright_header_shape_refuses_synthetic_value_leak(layers, kind):
    secrets = ["fresh-ansi-synthetic-" + str(index) + "-token-314159" for index in range(len(PRIVATE_HEADERS))]
    lines = ["route.fetch timeout15000ms GET /api/v1/report"]
    for header, secret in zip(sorted(PRIVATE_HEADERS), secrets, strict=True):
        # The actual cloud reporter uses dim SGR before its indented dash and
        # resets SGR after the header value. Split-name color is also admitted.
        colored = header[:2] + "\x1b[38:2::255:0:128m" + header[2:]
        lines.append("\x1b[2m    - " + colored + ": " + secret + "\x1b[22m")
    lines.extend(["\x1b[33mstatus:408 latency:14999.75 count:7\x1b[0m", "at original-report.spec.ts:42:9"])
    message = "\n".join(lines)
    for _ in range(layers):
        message = json.dumps(message)[1:-1]
    stats = {"expected": 0, "unexpected": 1, "skipped": 0, "flaky": 0, "duration": 15001.125}
    original = (json.dumps({"stats": stats, "suites": [{"error": {"message": message, "status": 408,
        "stack": "original-report.spec.ts:42:9", "exact_minor": 9000000000000000000}}]}).encode()
        if kind == "playwright.json" else message.encode())
    before = hashlib.sha256(original).hexdigest()
    result = derive_browser_diagnostic(kind, original, sanitizer_source_sha256=IDENTITY)
    text = result.content.decode()
    assert all(secret not in text for secret in secrets)
    assert "/api/v1/report" in text and "14999.75" in text and "original-report.spec.ts:42:9" in text
    if kind == "playwright.json":
        parsed = json.loads(text)
        assert parsed["stats"] == stats and parsed["suites"][0]["error"]["exact_minor"] == 9000000000000000000
    assert hashlib.sha256(original).hexdigest() == before == result.receipt["original_sha256"]


def test_ansi_named_header_records_and_colored_known_credential_are_classified_before_string_normalization():
    token = "fresh-colored-synthetic-value-271828"
    original = {"stats": {"duration": 12.75, "unexpected": 1}, "suites": [{"headers": [
        {"name": "\x1b[2mCookie\x1b[22m", "value": token},
        {"\x1b[2mX-ReconForge-CSRF\x1b[22m": token}],
        "message": "password=" + token[:10] + "\x1b[2m" + token[10:] + "\x1b[m status408"}]}
    result = derive_browser_diagnostic("playwright.json", json.dumps(original).encode(),
        sanitizer_source_sha256=IDENTITY, known_private_values=(token,))
    parsed = json.loads(result.content)
    assert token not in result.content.decode() and parsed["stats"] == original["stats"]
    assert parsed["suites"][0]["headers"][0] == {"name": "Cookie", "value": REDACTED}
    assert set(parsed["suites"][0]["headers"][1]) == set(original["suites"][0]["headers"][1])
    assert parsed["suites"][0]["headers"][1]["\x1b[2mX-ReconForge-CSRF\x1b[22m"] == REDACTED


@pytest.mark.parametrize("location", ["field_name", "artifact_path"])
def test_colored_known_private_field_or_path_is_refused_before_public_custody(location):
    token = "fresh-colored-private-location-161803"
    colored = token[:12] + "\x1b[2m" + token[12:] + "\x1b[22m"
    name = "playwright.json" if location == "field_name" else "playwright-artifacts/" + colored + "/error-context.md"
    raw = json.dumps({"stats": {}, "suites": [], colored: "unknown"}).encode() if location == "field_name" else b"safe"
    with pytest.raises(ValueError) as refused:
        derive_browser_diagnostic(name, raw, sanitizer_source_sha256=IDENTITY, known_private_values=(token,))
    assert token not in str(refused.value)
