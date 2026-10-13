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
from typing import Any

SANITIZER_VERSION = "browser-diagnostic-redaction-v2"
MAX_DIAGNOSTIC_BYTES = 64 * 1024 * 1024
MAX_JSON_NODES = 1_000_000
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
