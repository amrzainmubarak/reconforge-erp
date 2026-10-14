"""Synthetic adversarial diagnostics; no original credential packets are read."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.browser_diagnostic_redaction import (
    PRIVATE_HEADERS,
    REDACTED,
    derive_browser_diagnostic,
    derive_workspace_recovery_diagnostic,
    is_workspace_recovery_diagnostic_path,
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


WORKSPACE_PATH = "playwright-artifacts/workspace-recovery-cycles--abc123-ry-without-financial-replay-customer-returns-chromium/workspace-recovery-{locale}-original-native-boundary.json"
PRIVATE_SOURCE = "synthetic-financial-source-identifier-20261014"
PRIVATE_MONEY = "4500000000000000000.000000001"
STATIC_ASSET = "/assets/CustomerReturnsPage-syntheticBuild123.js"


def workspace_report(version="v1", locale="en"):
    original = {"stock": {"id": PRIVATE_SOURCE, "money": PRIVATE_MONEY, "quantity": 3,
                           "sourceSnapshots": [{"canonical_plan_json": "opaque original financial text"}]},
                "retained": {"plans": [{"id": PRIVATE_SOURCE, "total_minor": "9000000000000000000"}]},
                "balances": [{"id": PRIVATE_SOURCE, "original": {"balance": {"net_minor": "10001", "paid": None}}}]}
    report = {"schema_version": "workspace-recovery-native-" + version, "locale": locale,
        "injection": "One genuine CustomerReturnsPage JavaScript GET aborted; no API or financial response mocked",
        "originalBefore": original, "originalAfter": json.loads(json.dumps(original)), "pageErrors": [],
        "failedRequests": [{"path": STATIC_ASSET, "method": "GET", "kind": "script", "failure": "opaque failure " + PASSWORD}],
        "abortedAssets": [STATIC_ASSET], "financialMutations": [], "recovered": True,
        "rawFinancialOriginalsEqual": True, "fallbackHeadingCount": 0, "navigationCount": 1, "rootMainCount": 1,
        "previousBlankScreenCauseProven": False}
    if version == "v2":
        report["responsiveChecks"] = [{"width": width, "height": 900, "direction": "rtl" if locale == "ar" else "ltr",
            "overflowPixels": 0, "seriousCriticalViolationCount": 0, "primaryNavigationAvailable": True,
            "usedMobileMenu": width < 1024, "recoveryButtonsVisible": True} for width in (320, 768, 1024, 1440)]
    return report


def project_workspace(report, *, original=None, path=None):
    raw = json.dumps(report, ensure_ascii=False).encode() if original is None else original
    return derive_workspace_recovery_diagnostic(path or WORKSPACE_PATH.format(locale=report.get("locale", "en")), raw,
        sanitizer_source_sha256=IDENTITY, known_private_values=(SECRET, CSRF, PASSWORD))


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("locale", ["en", "ar"])
def test_private_recovery_profile_constructs_only_finite_public_scalars_without_original_mutation(version, locale):
    report = workspace_report(version, locale)
    raw = json.dumps(report, ensure_ascii=False).encode()
    before = hashlib.sha256(raw).hexdigest()
    result = project_workspace(report, original=raw)
    public = json.loads(result.content)
    assert set(public) == {"schema_version", "private_schema_version", "locale", "support_code", "recovery_reported",
        "recovery_verified", "financial_originals_equal", "financial_mutation_count", "page_error_count", "failed_request_count",
        "aborted_asset_count", "fallback_heading_count", "navigation_count", "root_main_count", "responsive_checks",
        "responsive_verified", "previous_blank_screen_cause_proven", "private_financial_originals_published", "original_bytes", "original_sha256"}
    assert public["locale"] == locale and public["private_schema_version"] == report["schema_version"]
    assert public["support_code"] == "RF-WORKSPACE-001" and public["recovery_verified"] is True
    assert public["financial_originals_equal"] is True and public["financial_mutation_count"] == 0
    assert public["responsive_verified"] is (version == "v2")
    assert len(public["responsive_checks"]) == (4 if version == "v2" else 0)
    assert public["previous_blank_screen_cause_proven"] is False and public["private_financial_originals_published"] is False
    assert set(result.receipt) == {"schema_version", "artifact_kind", "derived_relative_path", "original_bytes", "original_sha256",
        "derived_bytes", "derived_sha256", "sanitizer", "original_mutated", "financial_artifacts_sanitized", "private_financial_originals_published"}
    assert result.receipt["derived_relative_path"] == f"workspace-recovery/{locale}.json"
    assert result.receipt["original_sha256"] == public["original_sha256"] == before == hashlib.sha256(raw).hexdigest()
    assert result.receipt["derived_sha256"] == hashlib.sha256(result.content).hexdigest()
    assert result.receipt["original_bytes"] == public["original_bytes"] == len(raw)
    assert result.receipt["original_mutated"] is False and result.receipt["financial_artifacts_sanitized"] is False
    for private in (PRIVATE_SOURCE, PRIVATE_MONEY, STATIC_ASSET, SECRET, CSRF, PASSWORD, "canonical_plan_json", "originalBefore", "originalAfter"):
        assert private not in result.content.decode() and private not in json.dumps(result.receipt)
    assert json.loads(raw) == report


def test_original_negative_recovery_observations_remain_negative_and_error_contents_remain_private():
    report = workspace_report()
    report.update(recovered=False, navigationCount=0, rootMainCount=0)
    report["pageErrors"] = [{"name": "PrivateName" + SECRET, "message": "Cookie: " + SECRET + " Money=" + PRIVATE_MONEY,
                             "stack": PRIVATE_SOURCE + "\nAuthorization: " + CSRF}]
    result = project_workspace(report)
    public = json.loads(result.content)
    assert public["recovery_reported"] is public["recovery_verified"] is False
    assert public["page_error_count"] == 1 and public["financial_originals_equal"] is True
    assert "PrivateName" not in result.content.decode() and PRIVATE_SOURCE not in result.content.decode()


@pytest.mark.parametrize("difference", [False, 1, "3", None, {"replacement": 3}])
def test_financial_equality_is_computed_from_complete_private_typed_originals_and_forged_flag_refuses(difference):
    report = workspace_report()
    report["originalAfter"]["stock"]["quantity"] = difference
    report["rawFinancialOriginalsEqual"] = False
    public = json.loads(project_workspace(report).content)
    assert public["financial_originals_equal"] is False and public["recovery_verified"] is False
    report["rawFinancialOriginalsEqual"] = True
    with pytest.raises(ValueError):
        project_workspace(report)


def test_financial_equality_never_equates_boolean_true_with_integer_one_and_ignores_dictionary_order():
    report = workspace_report()
    report["originalBefore"]["stock"]["quantity"] = True
    report["originalAfter"]["stock"]["quantity"] = 1
    report["rawFinancialOriginalsEqual"] = False
    assert json.loads(project_workspace(report).content)["financial_originals_equal"] is False
    report["originalBefore"]["stock"]["quantity"] = 1
    report["originalAfter"]["stock"] = dict(reversed(list(report["originalBefore"]["stock"].items())))
    report["rawFinancialOriginalsEqual"] = True
    assert json.loads(project_workspace(report).content)["financial_originals_equal"] is True


def test_any_financial_mutation_or_extra_request_denies_recovery_verification_without_publishing_source_path():
    report = workspace_report()
    report["financialMutations"] = [{"path": "/api/v1/stock-sales/" + PRIVATE_SOURCE, "method": "POST"}]
    result = project_workspace(report)
    public = json.loads(result.content)
    assert public["financial_mutation_count"] == 1 and public["recovery_verified"] is False
    assert PRIVATE_SOURCE not in result.content.decode()
    report["financialMutations"] = []
    report["failedRequests"].append({"path": "/api/v1/private/" + PRIVATE_SOURCE, "method": "GET", "kind": "fetch", "failure": None})
    assert json.loads(project_workspace(report).content)["recovery_verified"] is False


@pytest.mark.parametrize("failure", [None, "", " \n\t"])
def test_missing_or_empty_static_failure_evidence_is_retained_without_verified_recovery(failure):
    report = workspace_report()
    report["failedRequests"][0]["failure"] = failure
    public = json.loads(project_workspace(report).content)
    assert public["failed_request_count"] == 1 and public["recovery_reported"] is True
    assert public["financial_originals_equal"] is True and public["recovery_verified"] is False


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_v2_responsive_failed_prefix_retains_negative_evidence_instead_of_claiming_complete_verification(count):
    report = workspace_report("v2")
    report["responsiveChecks"] = report["responsiveChecks"][:count]
    public = json.loads(project_workspace(report).content)
    assert len(public["responsive_checks"]) == count
    assert public["responsive_verified"] is public["recovery_verified"] is False


@pytest.mark.parametrize(("field", "value"), [("overflowPixels", 1), ("seriousCriticalViolationCount", 1),
    ("primaryNavigationAvailable", False), ("recoveryButtonsVisible", False), ("direction", "rtl")])
def test_v2_responsive_observed_failure_refuses_verified_success(field, value):
    report = workspace_report("v2")
    report["responsiveChecks"][0][field] = value
    public = json.loads(project_workspace(report).content)
    assert public["responsive_verified"] is public["recovery_verified"] is False


@pytest.mark.parametrize(("field", "value"), [("schema_version", []), ("schema_version", "workspace-recovery-native-v3"),
    ("locale", {}), ("locale", "de"), ("injection", "Mocked financial response"), ("recovered", 1),
    ("rawFinancialOriginalsEqual", 1), ("previousBlankScreenCauseProven", True), ("previousBlankScreenCauseProven", 0),
    ("fallbackHeadingCount", True), ("navigationCount", -1), ("rootMainCount", 33), ("pageErrors", None),
    ("failedRequests", {}), ("abortedAssets", [STATIC_ASSET, STATIC_ASSET]), ("abortedAssets", ["/assets/OtherPage.js"]),
    ("financialMutations", {}), ("originalBefore", {}), ("originalAfter", [])])
def test_private_recovery_exact_top_schema_types_and_domain_bounds_refuse(field, value):
    report = workspace_report()
    report[field] = value
    with pytest.raises(ValueError) as refused:
        project_workspace(report, path=WORKSPACE_PATH.format(locale="en"))
    assert PRIVATE_SOURCE not in str(refused.value) and SECRET not in str(refused.value)


@pytest.mark.parametrize("location", ["top", "error", "failed_request", "mutation", "original_wrapper", "retained", "balance_row", "balance_wrapper", "responsive"])
def test_unknown_or_raw_secret_extra_fields_are_rejected_before_any_projection(location):
    report = workspace_report("v2")
    if location == "top":
        target = report
    elif location == "error":
        report["pageErrors"] = [{"name": "Error", "message": "opaque", "stack": None}]
        target = report["pageErrors"][0]
    elif location == "failed_request":
        target = report["failedRequests"][0]
    elif location == "mutation":
        report["financialMutations"] = [{"path": "/api/v1/sensitive", "method": "POST"}]
        target = report["financialMutations"][0]
    elif location == "original_wrapper":
        target = report["originalBefore"]
    elif location == "retained":
        target = report["originalBefore"]["retained"]
    elif location == "balance_row":
        target = report["originalBefore"]["balances"][0]
    elif location == "balance_wrapper":
        target = report["originalBefore"]["balances"][0]["original"]
    else:
        target = report["responsiveChecks"][0]
    target["Cookie"] = SECRET
    with pytest.raises(ValueError) as refused:
        project_workspace(report)
    assert SECRET not in str(refused.value)


@pytest.mark.parametrize("field", ["password", "Authorization", "cookies", SECRET])
def test_opaque_private_financial_body_with_credential_field_never_enters_projection(field):
    report = workspace_report()
    report["originalBefore"]["stock"][field] = SECRET
    with pytest.raises(ValueError):
        project_workspace(report)


@pytest.mark.parametrize(("field", "value"), [("width", True), ("width", 768), ("height", 0), ("height", 16385),
    ("direction", {}), ("direction", "auto"), ("overflowPixels", False), ("overflowPixels", -1),
    ("seriousCriticalViolationCount", True), ("seriousCriticalViolationCount", 10001),
    ("primaryNavigationAvailable", 1), ("usedMobileMenu", 0), ("recoveryButtonsVisible", "true")])
def test_v2_responsive_scalar_schema_rejects_type_confusion_and_out_of_order_widths(field, value):
    report = workspace_report("v2")
    report["responsiveChecks"][0][field] = value
    with pytest.raises(ValueError):
        project_workspace(report)


@pytest.mark.parametrize("mutation", ["v1_extra_responsive", "v2_missing_responsive", "missing_field", "empty_balance_id", "missing_stock",
    "non_object_plan", "extra_balance_key", "unknown_method", "unknown_resource", "auth_mutation", "get_mutation", "missing_error_stack"])
def test_private_recovery_known_version_envelopes_and_events_fail_closed(mutation):
    report = workspace_report()
    if mutation == "v1_extra_responsive":
        report["responsiveChecks"] = []
    elif mutation == "v2_missing_responsive":
        report["schema_version"] = "workspace-recovery-native-v2"
    elif mutation == "missing_field":
        del report["recovered"]
    elif mutation == "empty_balance_id":
        report["originalBefore"]["balances"][0]["id"] = ""
    elif mutation == "missing_stock":
        report["originalBefore"]["stock"] = {}
    elif mutation == "non_object_plan":
        report["originalBefore"]["retained"]["plans"] = [None]
    elif mutation == "extra_balance_key":
        report["originalBefore"]["balances"][0]["original"]["balance2"] = {}
    elif mutation == "unknown_method":
        report["failedRequests"][0]["method"] = "TRACE"
    elif mutation == "unknown_resource":
        report["failedRequests"][0]["kind"] = "financial"
    elif mutation in {"auth_mutation", "get_mutation"}:
        report["financialMutations"] = [{"path": "/api/v1/auth/login" if mutation == "auth_mutation" else "/api/v1/sensitive",
                                         "method": "POST" if mutation == "auth_mutation" else "GET"}]
    else:
        report["pageErrors"] = [{"name": "Error", "message": PASSWORD}]
    with pytest.raises(ValueError):
        project_workspace(report)


@pytest.mark.parametrize("raw", [b"\xff", b"[]", b"null", b'{"schema_version":"workspace-recovery-native-v1","schema_version":"workspace-recovery-native-v1"}',
    b'{"private":NaN}', b'{"private":Infinity}', b'{"private":-Infinity}', b'{"private":1.0}'])
def test_malformed_duplicate_nonfinite_float_or_non_object_recovery_json_is_quarantined(raw):
    with pytest.raises(ValueError):
        project_workspace(workspace_report(), original=raw)


@pytest.mark.parametrize("mutation", ["float_original", "int_overflow", "deep_original", "long_array", "too_many_plans", "too_many_errors", "long_error", "node_ceiling", "byte_ceiling"])
def test_private_recovery_size_depth_node_and_exact_number_bounds_prevent_unbounded_processing(mutation):
    report = workspace_report()
    raw = None
    if mutation == "float_original":
        report["originalBefore"]["stock"]["quantity"] = 3.0
    elif mutation == "int_overflow":
        report["originalBefore"]["stock"]["quantity"] = 2**63
    elif mutation == "deep_original":
        nested = {}
        report["originalBefore"]["stock"]["deep"] = nested
        for _ in range(41):
            nested["child"] = {}
            nested = nested["child"]
    elif mutation == "long_array":
        report["originalBefore"]["stock"]["lines"] = [0] * 1001
    elif mutation == "too_many_plans":
        report["originalBefore"]["retained"]["plans"] = [{"id": "bounded"}] * 201
    elif mutation == "too_many_errors":
        report["pageErrors"] = [{"name": "Error", "message": "opaque", "stack": None}] * 65
    elif mutation == "long_error":
        report["pageErrors"] = [{"name": "Error", "message": "x" * 32769, "stack": None}]
    elif mutation == "node_ceiling":
        report["originalBefore"]["stock"]["lines"] = [[0] * 1000] * 101
    else:
        raw = b" " * (4 * 1024 * 1024 + 1)
    with pytest.raises(ValueError):
        project_workspace(report, original=raw)


@pytest.mark.parametrize("path", ["../workspace-recovery-en-original-native-boundary.json", "C:/workspace-recovery-en-original-native-boundary.json",
    "/playwright-artifacts/workspace-recovery-cycles--abc-customer-returns-chromium/workspace-recovery-en-original-native-boundary.json",
    "playwright-artifacts/other-case/workspace-recovery-en-original-native-boundary.json",
    WORKSPACE_PATH.format(locale="de"), WORKSPACE_PATH.format(locale="en") + "/extra", WORKSPACE_PATH.format(locale="en").replace("/", "\\"),
    WORKSPACE_PATH.format(locale="en").replace("abc123", "../abc123"), "oracle.json", "cashflow-original.json"])
def test_private_recovery_profile_never_admits_other_artifact_families_or_path_escape(path):
    assert is_workspace_recovery_diagnostic_path(path) is False
    with pytest.raises(ValueError):
        project_workspace(workspace_report(), path=path)


def test_private_profile_remains_separate_from_generic_diagnostics_and_locale_filename_must_match():
    path = WORKSPACE_PATH.format(locale="en")
    assert is_workspace_recovery_diagnostic_path(path) is True
    raw = json.dumps(workspace_report()).encode()
    with pytest.raises(ValueError, match="allowlist"):
        derive_browser_diagnostic(path, raw, sanitizer_source_sha256=IDENTITY)
    with pytest.raises(ValueError):
        project_workspace(workspace_report(locale="ar"), path=path)
    with pytest.raises(ValueError):
        derive_workspace_recovery_diagnostic(path, raw, sanitizer_source_sha256="uncaptured")
    with pytest.raises(ValueError):
        project_workspace(workspace_report(), path=path.replace("abc123", SECRET))


@pytest.mark.parametrize("private", ["RF-WORKSPACE-001", "ltr", IDENTITY])
def test_even_safe_constant_or_checksum_collision_with_known_private_value_refuses_publication(private):
    with pytest.raises(ValueError):
        derive_workspace_recovery_diagnostic(WORKSPACE_PATH.format(locale="en"), json.dumps(workspace_report("v2")).encode(),
            sanitizer_source_sha256=IDENTITY, known_private_values=(private,))
