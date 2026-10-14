"""Pure derived browser diagnostics; original financial artifacts are excluded.

The caller retains private originals and writes returned bytes to a separate
derived directory. This module performs no file, network or authentication work.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, NoReturn

SANITIZER_VERSION = "browser-diagnostic-redaction-v3"
MAX_DIAGNOSTIC_BYTES = 64 * 1024 * 1024
MAX_JSON_NODES = 1_000_000
MAX_WORKSPACE_RECOVERY_BYTES = 4 * 1024 * 1024
REDACTED = "[redacted]"
PRIVATE_HEADERS = frozenset({
    "cookie", "set-cookie", "authorization", "proxy-authorization",
    "x-reconforge-csrf", "x-csrf-token",
})
_NAMES = "(?:" + "|".join(re.escape(name) for name in sorted(PRIVATE_HEADERS, key=len, reverse=True)) + ")"
_QUOTED_FIELD = re.compile(
    r"(?<![A-Za-z0-9_./:-])(?P<quote>\\{0,31}[\"'])" + _NAMES
    + r"(?P=quote)[ \t]*:[ \t]*", re.IGNORECASE,
)
_PLAIN_FIELD = re.compile(
    r"(?:^|[\r\n]|\\+n|\\+r(?:\\+n)?)[ \t]*(?:-[ \t]*)?" + _NAMES + r"[ \t]*:[ \t]*",
    re.IGNORECASE,
)
_LINE_BREAK = re.compile(r"\r\n|[\r\n]|\\+r(?:\\+n)?|\\+n")
_QUOTE_START = re.compile(r"(?P<slashes>\\{0,31})(?P<quote>[\"'])")
_JSON_START = re.compile(r"(?m)^[ \t]*[\[{]")
_DIAGNOSTIC_SGR = re.compile(r"(?:\x1b|(?<!\\)\\+(?:u001[bB]|x1[bB]))\[[0-9;:]*m")


@dataclass(frozen=True)
class DerivedBrowserDiagnostic:
    content: bytes
    receipt: dict[str, Any]


def _private_variants(values: Iterable[str]) -> tuple[str, ...]:
    variants: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Known private browser values must be strings.")
        if not value:
            continue
        for original in {value, _DIAGNOSTIC_SGR.sub("", value)}:
            if not original:
                continue
            variants.add(original)
            for ascii_only in (False, True):
                escaped = original
                for _ in range(4):
                    escaped = json.dumps(escaped, ensure_ascii=ascii_only)[1:-1]
                    variants.add(escaped)
    if any(value in REDACTED for value in variants):
        raise ValueError("Known private browser value conflicts with the redaction marker.")
    return tuple(sorted(variants, key=lambda value: (-len(value), value)))


def _quote_end(value: str, start: int, slashes: int, quote: str) -> int | None:
    # JSON layers use quote prefixes 0,1,3,7,... backslashes. Closing quotes
    # remain distinguishable from an embedded escaped quote at each layer.
    modulus = 2 * (slashes + 1)
    position = start
    while position < len(value):
        position = value.find(quote, position)
        if position < 0:
            return None
        prefix = position
        while prefix > start and value[prefix - 1] == "\\":
            prefix -= 1
        count = position - prefix
        if count >= slashes and (count - slashes) % modulus == 0:
            return position - slashes
        position += 1
    return None


def _plain_end(value: str, start: int) -> int:
    boundary = _LINE_BREAK.search(value, start)
    end = boundary.start() if boundary else len(value)
    # Retain a surrounding JSON/string delimiter when the header is the
    # last line in an embedded error string, including its closing braces.
    tail = re.search(r"[\"'](?=[ \t]*[,}\]]*[ \t]*$)", value[start:end])
    return start + tail.start() if tail else end


def _redact_header_fields(value: str, pattern: re.Pattern[str]) -> str:
    pieces: list[str] = []
    position = 0
    while match := pattern.search(value, position):
        start = match.end()
        quote = _QUOTE_START.match(value, start)
        if quote:
            delimiter_end = quote.end()
            end = _quote_end(value, delimiter_end, len(quote["slashes"]), quote["quote"])
            if end is None:
                end = _plain_end(value, delimiter_end)
            pieces.extend((value[position:delimiter_end], REDACTED))
        else:
            end = _plain_end(value, start)
            pieces.extend((value[position:start], REDACTED))
        if end < start:
            raise ValueError("Browser diagnostic header boundary is invalid.")
        position = end
    pieces.append(value[position:])
    return "".join(pieces)


def redact_browser_text(value: str, known_private_values: Iterable[str] = ()) -> str:
    """Remove header values and known credentials without decoding trace text."""
    if not isinstance(value, str):
        raise ValueError("Browser diagnostic text must be a string.")
    # Playwright places ANSI dim/reset SGR before its indented header lines.
    # Normalize actual and JSON-reescaped diagnostic styling before parsing;
    # never decode arbitrary Unicode escapes or alter an original artifact.
    value = _DIAGNOSTIC_SGR.sub("", value)
    private = tuple(known_private_values)
    variants = _private_variants(private)
    # Playwright's JSON reporter can be embedded after ordinary stdout. Parse
    # whole container fragments so a last header line cannot consume its
    # surrounding JSON fields or numeric stats. No financial file is read.
    decoder = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_nonfinite)
    parts: list[str] = []
    position = 0
    attempts = 0
    for match in _JSON_START.finditer(value):
        start = match.end() - 1
        if start < position:
            continue
        attempts += 1
        if attempts > 1000:
            raise ValueError("Browser diagnostic JSON fragment count exceeds its bound.")
        try:
            container, end = decoder.raw_decode(value, start)
        except json.JSONDecodeError:
            continue
        if isinstance(container, (dict, list)):
            prefix = _redact_header_fields(value[position:start], _QUOTED_FIELD)
            parts.append(_redact_header_fields(prefix, _PLAIN_FIELD))
            parts.append(json.dumps(redact_playwright_value(container, private), ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")))
            position = end
    suffix = _redact_header_fields(value[position:], _QUOTED_FIELD)
    parts.append(_redact_header_fields(suffix, _PLAIN_FIELD))
    result = "".join(parts)
    for variant in variants:
        result = result.replace(variant, REDACTED)
    return result


def redact_playwright_value(value: Any, known_private_values: Iterable[str] = ()) -> Any:
    """Change string values only; retain keys, numeric stats and array shapes."""
    private = tuple(known_private_values)
    variants = _private_variants(private)
    nodes = 0

    def walk(current: Any, *, force: bool = False, depth: int = 0) -> Any:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > 100:
            raise ValueError("Playwright diagnostic exceeds its structural bound.")
        if isinstance(current, str):
            return REDACTED if force else redact_browser_text(current, private)
        if isinstance(current, list):
            return [walk(item, force=force, depth=depth + 1) for item in current]
        if isinstance(current, dict):
            named_header = isinstance(current.get("name"), str) and _DIAGNOSTIC_SGR.sub("", current["name"]).lower() in PRIVATE_HEADERS
            result = {}
            for key, item in current.items():
                if not isinstance(key, str) or any(variant in key or variant in _DIAGNOSTIC_SGR.sub("", key) for variant in variants):
                    raise ValueError("Playwright diagnostic field name cannot be published safely.")
                result[key] = walk(item, force=force or _DIAGNOSTIC_SGR.sub("", key).lower() in PRIVATE_HEADERS
                                   or named_header and key == "value", depth=depth + 1)
            return result
        if current is None or type(current) in (int, float, bool):
            return current
        raise ValueError("Playwright diagnostic contains an unsupported value.")

    return walk(value)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({key for key, _ in items}) != len(items):
        raise ValueError("Playwright diagnostic contains duplicate fields.")
    return dict(items)


def _nonfinite(_: str) -> Any:
    raise ValueError("Playwright diagnostic contains a nonfinite number.")


def derive_browser_diagnostic(
    relative_path: str, original: bytes, *, sanitizer_source_sha256: str,
    known_private_values: Iterable[str] = (),
) -> DerivedBrowserDiagnostic:
    """Return a separate diagnostic and value-free raw custody receipt.

    The helper's source SHA is independently computed and supplied by the caller.
    Only browser.log, the common runner's playwright.json and nested Playwright
    error-context.md artifacts are admitted. No file is opened or overwritten.
    """
    if not isinstance(relative_path, str) or "\\" in relative_path:
        raise ValueError("Browser diagnostic requires a normalized relative artifact path.")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ":" in relative_path or any(part in {".", ".."} for part in relative_path.split("/")):
        raise ValueError("Browser diagnostic path escapes its artifact scope.")
    kind = ("playwright-report" if relative_path == "playwright.json"
            else "browser-log" if relative_path == "browser.log"
            else "error-context" if len(path.parts) >= 3 and path.parts[0] == "playwright-artifacts"
            and path.name == "error-context.md" else None)
    if kind is None:
        raise ValueError("Artifact is outside the browser diagnostic redaction allowlist.")
    if not isinstance(original, bytes) or len(original) > MAX_DIAGNOSTIC_BYTES:
        raise ValueError("Browser diagnostic bytes exceed their explicit bound.")
    if not isinstance(sanitizer_source_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sanitizer_source_sha256) is None:
        raise ValueError("A captured sanitizer source identity is required.")
    private = tuple(known_private_values)
    if any(variant in relative_path or variant in _DIAGNOSTIC_SGR.sub("", relative_path) for variant in _private_variants(private)):
        raise ValueError("Browser diagnostic artifact path cannot be published safely.")
    try:
        text = original.decode("utf-8")
        if kind == "playwright-report":
            report = json.loads(text, object_pairs_hook=_pairs, parse_constant=_nonfinite)
            if not isinstance(report, dict) or not isinstance(report.get("stats"), dict) or not isinstance(report.get("suites"), list):
                raise ValueError("A structured Playwright diagnostic report is required.")
            sanitized = json.dumps(redact_playwright_value(report, private), ensure_ascii=False, allow_nan=False,
                                   separators=(",", ":")).encode("utf-8")
        else:
            sanitized = redact_browser_text(text, private).encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Browser diagnostic is not valid UTF-8 or structured report JSON.") from exc
    return DerivedBrowserDiagnostic(sanitized, {
        "schema_version": "derived-browser-diagnostic-custody-v1",
        "artifact_kind": kind, "original_relative_path": relative_path,
        "original_bytes": len(original), "original_sha256": hashlib.sha256(original).hexdigest(),
        "derived_bytes": len(sanitized), "derived_sha256": hashlib.sha256(sanitized).hexdigest(),
        "sanitizer": {"version": SANITIZER_VERSION, "source_sha256": sanitizer_source_sha256},
        "original_mutated": False, "financial_artifacts_sanitized": False,
    })


def is_workspace_recovery_diagnostic_path(relative_path: str) -> bool:
    """Recognize one private producer family without expanding generic publication."""
    return type(relative_path) is str and re.fullmatch(
        r"playwright-artifacts/workspace-recovery-cycles--[A-Za-z0-9_-]{1,200}-customer-returns-chromium/"
        r"workspace-recovery-(?:en|ar)-original-native-boundary\.json", relative_path,
    ) is not None


def _workspace_invalid() -> NoReturn:
    raise ValueError("Workspace recovery diagnostic violates its finite private projection contract.")


def _workspace_object(value: Any, fields: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        return _workspace_invalid()
    return value


def _workspace_integer(value: Any, maximum: int, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        return _workspace_invalid()
    return value


def _workspace_string(value: Any, maximum: int, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or len(value) > maximum:
        _workspace_invalid()


def _workspace_list(value: Any, maximum: int) -> list[Any]:
    if type(value) is not list or len(value) > maximum:
        return _workspace_invalid()
    return value


def _workspace_original(value: Any, private_variants: tuple[str, ...]) -> str:
    """Validate finite envelopes and opaque typed originals; prove no ledger claim."""
    wrapper = _workspace_object(value, {"stock", "retained", "balances"})
    if type(wrapper["stock"]) is not dict or not wrapper["stock"]:
        _workspace_invalid()
    retained = _workspace_object(wrapper["retained"], {"plans"})
    for plan in _workspace_list(retained["plans"], 200):
        if type(plan) is not dict or not plan:
            _workspace_invalid()
    for balance in _workspace_list(wrapper["balances"], 200):
        row = _workspace_object(balance, {"id", "original"})
        _workspace_string(row["id"], 160)
        if not row["id"]:
            _workspace_invalid()
        original = _workspace_object(row["original"], {"balance"})
        if type(original["balance"]) is not dict or not original["balance"]:
            _workspace_invalid()
    nodes = 0
    forbidden = PRIVATE_HEADERS | {"password", "token", "secret", "headers", "cookies", "credentials", "csrf_token", "api_key", "client_secret"}

    def walk(current: Any, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 100_000 or depth > 40:
            _workspace_invalid()
        if type(current) is dict:
            for key, item in current.items():
                if (type(key) is not str or len(key) > 256 or key.lower() in forbidden
                        or any(variant in key for variant in private_variants)):
                    _workspace_invalid()
                walk(item, depth + 1)
        elif type(current) is list:
            if len(current) > 1000:
                _workspace_invalid()
            for item in current:
                walk(item, depth + 1)
        elif type(current) is str:
            if len(current) > 2_000_000:
                _workspace_invalid()
        elif type(current) is int:
            if not -(2**63) <= current <= 2**63 - 1:
                _workspace_invalid()
        elif current is not None and type(current) is not bool:
            _workspace_invalid()

    walk(wrapper)
    # JSON type tags distinguish true from 1 and every string from an integer.
    # Complete private bodies are never copied into the derived projection.
    return json.dumps(wrapper, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def derive_workspace_recovery_diagnostic(
    relative_path: str, original: bytes, *, sanitizer_source_sha256: str,
    known_private_values: Iterable[str] = (),
) -> DerivedBrowserDiagnostic:
    """Derive scalar recovery evidence; preserve all raw financial originals privately."""
    if (not is_workspace_recovery_diagnostic_path(relative_path) or type(original) is not bytes
            or len(original) > MAX_WORKSPACE_RECOVERY_BYTES or type(sanitizer_source_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", sanitizer_source_sha256) is None):
        _workspace_invalid()
    private = _private_variants(known_private_values)
    if any(variant in relative_path for variant in private):
        _workspace_invalid()
    try:
        report = json.loads(original.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite,
                            parse_float=lambda _: _workspace_invalid())
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        _workspace_invalid()
    fields = {"schema_version", "locale", "injection", "originalBefore", "originalAfter", "pageErrors", "failedRequests",
              "abortedAssets", "financialMutations", "recovered", "rawFinancialOriginalsEqual", "fallbackHeadingCount",
              "navigationCount", "rootMainCount", "previousBlankScreenCauseProven"}
    if type(report) is dict and report.get("schema_version") == "workspace-recovery-native-v2":
        fields.add("responsiveChecks")
    report = _workspace_object(report, fields)
    if (type(report["schema_version"]) is not str
            or report["schema_version"] not in {"workspace-recovery-native-v1", "workspace-recovery-native-v2"}
            or type(report["locale"]) is not str or report["locale"] not in {"en", "ar"}
            or not relative_path.endswith(f"workspace-recovery-{report['locale']}-original-native-boundary.json")
            or type(report["injection"]) is not str
            or report["injection"] != "One genuine CustomerReturnsPage JavaScript GET aborted; no API or financial response mocked"):
        _workspace_invalid()
    for field in ("recovered", "rawFinancialOriginalsEqual", "previousBlankScreenCauseProven"):
        if type(report[field]) is not bool:
            _workspace_invalid()
    if report["previousBlankScreenCauseProven"]:
        _workspace_invalid()  # This injected test cannot attribute the historical failure.
    counts = {field: _workspace_integer(report[field], 32) for field in ("fallbackHeadingCount", "navigationCount", "rootMainCount")}
    before = _workspace_original(report["originalBefore"], private)
    after = _workspace_original(report["originalAfter"], private)
    equal = before == after
    if report["rawFinancialOriginalsEqual"] is not equal:
        _workspace_invalid()
    errors = _workspace_list(report["pageErrors"], 64)
    for error in errors:
        row = _workspace_object(error, {"name", "message", "stack"})
        _workspace_string(row["name"], 128)
        _workspace_string(row["message"], 32_768)
        _workspace_string(row["stack"], 65_536, nullable=True)
    failed = _workspace_list(report["failedRequests"], 64)
    resources = {"document", "stylesheet", "image", "media", "font", "script", "texttrack", "xhr", "fetch", "eventsource", "websocket", "manifest", "other"}
    methods = {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}
    for request in failed:
        row = _workspace_object(request, {"path", "method", "kind", "failure"})
        _workspace_string(row["path"], 2048)
        _workspace_string(row["failure"], 256, nullable=True)
        if type(row["method"]) is not str or row["method"] not in methods or type(row["kind"]) is not str or row["kind"] not in resources:
            _workspace_invalid()
    aborted = _workspace_list(report["abortedAssets"], 1)
    for asset in aborted:
        if type(asset) is not str or re.fullmatch(r"/assets/CustomerReturnsPage-[A-Za-z0-9_-]{1,128}\.js", asset) is None:
            _workspace_invalid()
    mutations = _workspace_list(report["financialMutations"], 64)
    for mutation in mutations:
        row = _workspace_object(mutation, {"path", "method"})
        _workspace_string(row["path"], 2048)
        if (not row["path"].startswith("/api/v1/") or row["path"].startswith("/api/v1/auth/")
                or type(row["method"]) is not str or row["method"] not in methods - {"GET", "HEAD", "OPTIONS"}):
            _workspace_invalid()
    responsive = []
    widths = (320, 768, 1024, 1440)
    if report["schema_version"] == "workspace-recovery-native-v2":
        for index, item in enumerate(_workspace_list(report["responsiveChecks"], 4)):
            row = _workspace_object(item, {"width", "height", "direction", "overflowPixels", "seriousCriticalViolationCount",
                                           "primaryNavigationAvailable", "usedMobileMenu", "recoveryButtonsVisible"})
            width = _workspace_integer(row["width"], 1440)
            if width != widths[index] or type(row["direction"]) is not str or row["direction"] not in {"ltr", "rtl"}:
                _workspace_invalid()
            for flag in ("primaryNavigationAvailable", "usedMobileMenu", "recoveryButtonsVisible"):
                if type(row[flag]) is not bool:
                    _workspace_invalid()
            responsive.append({"width": width, "height": _workspace_integer(row["height"], 16_384, minimum=1),
                "direction": row["direction"], "overflow_pixels": _workspace_integer(row["overflowPixels"], 1_000_000),
                "serious_critical_violation_count": _workspace_integer(row["seriousCriticalViolationCount"], 10_000),
                "primary_navigation_available": row["primaryNavigationAvailable"], "used_mobile_menu": row["usedMobileMenu"],
                "recovery_buttons_visible": row["recoveryButtonsVisible"]})
    responsive_verified = len(responsive) == 4 and all(row["direction"] == ("rtl" if report["locale"] == "ar" else "ltr")
        and row["overflow_pixels"] == row["serious_critical_violation_count"] == 0
        and row["primary_navigation_available"] and row["recovery_buttons_visible"] for row in responsive)
    injected_static_failure = len(aborted) == len(failed) == 1 and failed[0]["path"] == aborted[0] and failed[0]["method"] == "GET" and failed[0]["kind"] == "script"
    verified = (report["recovered"] and equal and not errors and not mutations and injected_static_failure
                and counts == {"fallbackHeadingCount": 0, "navigationCount": 1, "rootMainCount": 1}
                and (report["schema_version"] == "workspace-recovery-native-v1" or responsive_verified))
    derived = {"schema_version": "workspace-recovery-public-v1", "private_schema_version": report["schema_version"],
        "locale": report["locale"], "support_code": "RF-WORKSPACE-001",
        "recovery_reported": report["recovered"], "recovery_verified": verified, "financial_originals_equal": equal,
        "financial_mutation_count": len(mutations), "page_error_count": len(errors), "failed_request_count": len(failed),
        "aborted_asset_count": len(aborted), "fallback_heading_count": counts["fallbackHeadingCount"],
        "navigation_count": counts["navigationCount"], "root_main_count": counts["rootMainCount"],
        "responsive_checks": responsive, "responsive_verified": responsive_verified,
        "previous_blank_screen_cause_proven": False, "private_financial_originals_published": False,
        "original_bytes": len(original), "original_sha256": hashlib.sha256(original).hexdigest()}
    sanitized = json.dumps(derived, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
    receipt = {"schema_version": "derived-browser-diagnostic-custody-v1",
        "artifact_kind": "workspace-recovery-projection", "derived_relative_path": f"workspace-recovery/{report['locale']}.json",
        "original_bytes": len(original), "original_sha256": hashlib.sha256(original).hexdigest(),
        "derived_bytes": len(sanitized), "derived_sha256": hashlib.sha256(sanitized).hexdigest(),
        "sanitizer": {"version": SANITIZER_VERSION, "source_sha256": sanitizer_source_sha256},
        "original_mutated": False, "financial_artifacts_sanitized": False, "private_financial_originals_published": False}
    published = sanitized.decode("ascii") + json.dumps(receipt, ensure_ascii=True, allow_nan=False)
    if any(variant in published for variant in private):
        _workspace_invalid()
    return DerivedBrowserDiagnostic(sanitized, receipt)
