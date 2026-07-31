"""Money utilities."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from importlib.resources import files
from inspect import currentframe
from pathlib import Path
from threading import RLock
from typing import Any, ClassVar, Literal, cast


class InvalidAmountError(ValueError):
    """Raised when a financial value cannot be interpreted safely."""


class LegacyFinancialInputWarning(DeprecationWarning):
    """Warn that a compatibility reader accepted binary floating-point input."""


LEGACY_FINANCIAL_INPUT_POLICY: Literal["legacy-financial-input-v1"] = "legacy-financial-input-v1"
STRICT_FINANCIAL_INPUT_POLICY: Literal["strict-financial-input-v2"] = "strict-financial-input-v2"
FinancialInputPolicy = Literal[
    "legacy-financial-input-v1",
    "strict-financial-input-v2",
]
CURRENT_FINANCIAL_INPUT_POLICY: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY


_SCIENTIFIC_NOTATION_PATTERN = re.compile(r"[eE]")
_CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")
_NUMERIC_CURRENCY_CODE_PATTERN = re.compile(r"^[0-9]{3}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REGISTRY_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}$")
_CURRENCY_REGISTRY_SCHEMA_VERSION = 1
_BUNDLED_CURRENCY_REGISTRY = "currency_registry.v1.json"
_MAX_CURRENCY_REGISTRY_BYTES = 1_000_000
_MAX_CURRENCIES = 1_000
_ROUNDING_POLICIES = {"ROUND_HALF_UP": ROUND_HALF_UP}
_LEGACY_WARNING_CALL_SITES: set[tuple[str, int]] = set()
_LEGACY_WARNING_LOCK = RLock()


def _is_binary_floating_point(value: object) -> bool:
    """Recognize Python and NumPy floating scalars without importing NumPy."""

    if isinstance(value, float):
        return True
    return any(base.__module__.startswith("numpy") and base.__name__ == "floating" for base in type(value).__mro__)


def _warn_legacy_financial_input_once(*, stacklevel: int = 2) -> None:
    """Emit one deprecation warning per external source call site."""

    frame = currentframe()
    caller = frame
    try:
        for _ in range(stacklevel):
            caller = caller.f_back if caller is not None else None
        key = (
            caller.f_code.co_filename if caller is not None else "<unknown>",
            caller.f_lineno if caller is not None else 0,
        )
    finally:
        del caller
        del frame
    with _LEGACY_WARNING_LOCK:
        if key in _LEGACY_WARNING_CALL_SITES:
            return
        _LEGACY_WARNING_CALL_SITES.add(key)
    warnings.warn(
        "binary floating-point financial input is deprecated; pass Decimal, integer, or exact text",
        LegacyFinancialInputWarning,
        stacklevel=stacklevel + 1,
    )


def validate_financial_input_policy(value: object) -> FinancialInputPolicy:
    """Return a supported financial-input policy or fail without echoing input data."""

    if value in {LEGACY_FINANCIAL_INPUT_POLICY, STRICT_FINANCIAL_INPUT_POLICY}:
        return cast(FinancialInputPolicy, value)
    raise InvalidAmountError("unsupported financial input policy")


def _rounding_mode(policy: str) -> str:
    try:
        return _ROUNDING_POLICIES[policy]
    except KeyError as exc:
        raise InvalidAmountError(f"unsupported financial rounding policy: {policy}") from exc


def _quantize_decimal(value: Decimal, *, precision: int, rounding_policy: str) -> Decimal:
    """Quantize with enough local precision for large, finite financial values."""

    if precision < 0 or precision > 8:
        raise InvalidAmountError("financial precision must be between 0 and 8")
    quant = Decimal("1").scaleb(-precision)
    integer_digits = max(1, value.adjusted() + 1) if value else 1
    required_precision = max(28, len(value.as_tuple().digits) + 2, integer_digits + precision + 2)
    try:
        with localcontext() as context:
            context.prec = required_precision
            return value.quantize(quant, rounding=_rounding_mode(rounding_policy))
    except InvalidOperation as exc:
        raise InvalidAmountError("financial amount cannot be represented at configured precision") from exc


def _exact_add(left: Decimal, right: Decimal, *, subtract: bool = False) -> Decimal:
    values = (left, right)
    max_adjusted = max((value.adjusted() for value in values if value), default=0)
    min_exponent = min(
        (int(value.as_tuple().exponent) for value in values),
        default=0,
    )
    required_precision = max(28, max_adjusted - min_exponent + 3)
    with localcontext() as context:
        context.prec = required_precision
        return left - right if subtract else left + right


def _exact_multiply(left: Decimal, right: Decimal) -> Decimal:
    required_precision = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2)
    with localcontext() as context:
        context.prec = required_precision
        return left * right


def _divide_for_money(
    numerator: Decimal,
    denominator: Decimal,
    *,
    precision: int,
    rounding_policy: str,
) -> Decimal:
    integer_digits = max(1, numerator.adjusted() - denominator.adjusted() + 2) if numerator else 1
    required_precision = max(
        34,
        integer_digits + precision + 18,
        len(numerator.as_tuple().digits) + len(denominator.as_tuple().digits) + precision + 8,
    )
    with localcontext() as context:
        context.prec = required_precision
        context.rounding = _rounding_mode(rounding_policy)
        quotient = numerator / denominator
    return _quantize_decimal(quotient, precision=precision, rounding_policy=rounding_policy)


def _normalize_financial_text(
    text: str,
    *,
    decimal_separator: str | None,
    thousands_separator: str | None,
) -> str:
    """Normalize separator variants into a Decimal-compatible numeric representation."""

    cleaned = text.strip()
    if decimal_separator is None and thousands_separator is None:
        return cleaned.replace(",", "")
    if decimal_separator is None:
        decimal_separator = "."
    if thousands_separator is None:
        return cleaned.replace(decimal_separator, ".")

    if thousands_separator and thousands_separator == decimal_separator:
        raise InvalidAmountError("financial separators must be distinct")
    normalized = cleaned.replace(" ", "")
    normalized = normalized.replace(thousands_separator, "")
    if decimal_separator != ".":
        normalized = normalized.replace(decimal_separator, ".")
    return normalized


def parse_amount(
    value: object,
    *,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    _warn_on_legacy_input: bool = True,
) -> Decimal:
    """Parse a finite financial amount without silently substituting zero.

    Comma group separators and conventional accounting parentheses are
    accepted by default. Optional locale separators can be provided for
    decimal-parsing flexibility.
    """

    input_policy = validate_financial_input_policy(input_policy)
    legacy_binary_input = _is_binary_floating_point(value)
    if legacy_binary_input and input_policy == STRICT_FINANCIAL_INPUT_POLICY:
        raise InvalidAmountError("binary floating-point financial input is not allowed under strict-financial-input-v2")
    if value is None or isinstance(value, bool):
        raise InvalidAmountError("financial amount is missing or invalid")
    if decimal_separator is not None and (len(decimal_separator) != 1 or decimal_separator.isspace()):
        raise InvalidAmountError("financial amount separator must be a single non-space character")
    if thousands_separator is not None and (len(thousands_separator) != 1 or thousands_separator.isspace()):
        raise InvalidAmountError("financial amount separator must be a single non-space character")

    text = str(value).strip()
    if not text or text.casefold() in {"nan", "nat", "none", "null", "n/a"}:
        raise InvalidAmountError("financial amount is missing or invalid")
    if not isinstance(value, Decimal) and _SCIENTIFIC_NOTATION_PATTERN.search(text):
        raise InvalidAmountError("financial amount in scientific notation is not allowed")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    normalized = _normalize_financial_text(
        text,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
    )
    if not isinstance(value, Decimal) and _SCIENTIFIC_NOTATION_PATTERN.search(normalized):
        raise InvalidAmountError("financial amount in scientific notation is not allowed")
    try:
        parsed = Decimal(normalized)
    except InvalidOperation as exc:
        raise InvalidAmountError("financial amount is not numeric") from exc
    if not parsed.is_finite():
        raise InvalidAmountError("financial amount must be finite")
    if legacy_binary_input and _warn_on_legacy_input:
        _warn_legacy_financial_input_once()
    return -parsed if negative else parsed


def parse_exact_amount(
    value: object,
    *,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal:
    """Parse an amount under the current strict financial-input policy."""

    return parse_amount(
        value,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )


def parse_amount_for_currency_precision(
    value: object,
    *,
    precision: int,
    rounding_policy: str = "ROUND_HALF_UP",
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    _warn_on_legacy_input: bool = True,
) -> Decimal:
    """Parse and validate a financial value for a specific currency precision.

    Inputs with greater fractional precision than the currency allows are rejected
    rather than silently rounded.
    """

    legacy_binary_input = _is_binary_floating_point(value)
    parsed = parse_amount(
        value,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
        input_policy=input_policy,
        _warn_on_legacy_input=False,
    )
    if legacy_binary_input and input_policy == LEGACY_FINANCIAL_INPUT_POLICY and _warn_on_legacy_input:
        _warn_legacy_financial_input_once()
    quantized = _quantize_decimal(parsed, precision=precision, rounding_policy=rounding_policy)
    if parsed != quantized:
        raise InvalidAmountError("financial amount exceeds configured currency precision")
    return quantized


def parse_exact_amount_for_currency_precision(
    value: object,
    *,
    precision: int,
    rounding_policy: str = "ROUND_HALF_UP",
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal:
    """Parse a currency amount under the current strict financial-input policy."""

    return parse_amount_for_currency_precision(
        value,
        precision=precision,
        rounding_policy=rounding_policy,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )


def round_money(
    value: float | int | str | Decimal | None,
    places: int = 2,
    *,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal:
    """Round a monetary value using accounting-friendly half-up behavior."""

    decimal_value = parse_amount(
        value,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
        input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
    )
    return _quantize_decimal(decimal_value, precision=places, rounding_policy="ROUND_HALF_UP")


def round_exact_money(
    value: object,
    places: int = 2,
    *,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal:
    """Round an amount after enforcing the current strict input policy.

    This is the current internal scalar-rounding entry point. ``round_money``
    remains the public legacy-v1 compatibility reader until a breaking-release
    boundary.
    """

    decimal_value = parse_exact_amount(
        value,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
    )
    return _quantize_decimal(decimal_value, precision=places, rounding_policy="ROUND_HALF_UP")


def money_difference(
    left: float | int | str | Decimal | None,
    right: float | int | str | Decimal | None,
    *,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal:
    """Return a rounded absolute difference between two amounts."""

    return abs(
        round_money(
            left,
            decimal_separator=decimal_separator,
            thousands_separator=thousands_separator,
        )
        - round_money(
            right,
            decimal_separator=decimal_separator,
            thousands_separator=thousands_separator,
        )
    )


def exact_money_difference(
    left: object,
    right: object,
    *,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal:
    """Return a rounded absolute difference under strict financial input v2."""

    return abs(
        round_exact_money(
            left,
            decimal_separator=decimal_separator,
            thousands_separator=thousands_separator,
        )
        - round_exact_money(
            right,
            decimal_separator=decimal_separator,
            thousands_separator=thousands_separator,
        )
    )


def within_tolerance(
    left: float | int | str | Decimal | None,
    right: float | int | str | Decimal | None,
    tolerance: float | int | str | Decimal,
    *,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> bool:
    """Return true when two monetary values are within the configured tolerance."""

    return money_difference(
        left,
        right,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
    ) <= round_money(
        tolerance,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
    )


def within_exact_tolerance(
    left: object,
    right: object,
    tolerance: object,
    *,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> bool:
    """Compare exact financial inputs under the current strict policy."""

    return exact_money_difference(
        left,
        right,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
    ) <= round_exact_money(
        tolerance,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
    )


class CurrencyMismatchError(ValueError):
    """Raised when an arithmetic or comparison operation is attempted on incompatible currencies."""


class CurrencyPolicyMismatchError(CurrencyMismatchError):
    """Raised when equal currency codes use different precision or rounding policies."""


class UnknownCurrencyError(InvalidAmountError):
    """Raised when a currency code has no explicit registered financial policy."""


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _sha256_payload(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _json_without_duplicate_keys(text: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise InvalidAmountError(f"currency registry contains duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise InvalidAmountError("currency registry is not valid UTF-8 JSON") from exc


@dataclass(frozen=True)
class CurrencySpec:
    """One explicit currency precision and rounding policy."""

    code: str
    name: str
    minor_units: int = 2
    symbol: str = ""
    numeric_code: str = ""
    rounding_policy: str = "ROUND_HALF_UP"

    def __post_init__(self) -> None:
        code = str(self.code).strip().upper()
        name = str(self.name).strip()
        symbol = str(self.symbol).strip()
        numeric_code = str(self.numeric_code).strip()
        rounding_policy = str(self.rounding_policy).strip().upper()
        if not code:
            raise InvalidAmountError("currency code cannot be empty")
        if not _CURRENCY_CODE_PATTERN.fullmatch(code):
            raise InvalidAmountError("currency code must contain exactly three ASCII letters")
        if not name or len(name) > 200:
            raise InvalidAmountError("currency name must contain between 1 and 200 characters")
        if isinstance(self.minor_units, bool) or not isinstance(self.minor_units, int):
            raise InvalidAmountError("minor_units must be an integer")
        if not 0 <= self.minor_units <= 8:
            raise InvalidAmountError("minor_units must be between 0 and 8")
        if numeric_code and not _NUMERIC_CURRENCY_CODE_PATTERN.fullmatch(numeric_code):
            raise InvalidAmountError("numeric currency code must contain exactly three digits")
        if len(symbol) > 16:
            raise InvalidAmountError("currency symbol must not exceed 16 characters")
        _rounding_mode(rounding_policy)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "numeric_code", numeric_code)
        object.__setattr__(self, "rounding_policy", rounding_policy)

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic registry representation."""

        return {
            "code": self.code,
            "minor_units": self.minor_units,
            "name": self.name,
            "numeric_code": self.numeric_code,
            "rounding_policy": self.rounding_policy,
            "symbol": self.symbol,
        }

    @property
    def policy_digest(self) -> str:
        """Digest only the attributes that can change financial value semantics."""

        return _sha256_payload(
            {
                "code": self.code,
                "minor_units": self.minor_units,
                "rounding_policy": self.rounding_policy,
            },
        )


@dataclass(frozen=True)
class CurrencyRegistryManifest:
    """Version and integrity metadata for one installed registry snapshot."""

    schema_version: int
    registry_version: str
    source: str
    source_url: str
    published_at: str
    digest: str
    currency_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "currency_count": self.currency_count,
            "digest": self.digest,
            "published_at": self.published_at,
            "registry_version": self.registry_version,
            "schema_version": self.schema_version,
            "source": self.source,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class ResolvedCurrencyPolicy:
    """Currency policy and registry provenance captured as one atomic resolution."""

    spec: CurrencySpec
    registry_version: str
    registry_digest: str

    @property
    def policy_digest(self) -> str:
        return self.spec.policy_digest


class CurrencyRegistry:
    """Atomic, versioned, offline currency-policy registry.

    Unknown codes fail closed. Updates are explicit and can be installed from a
    bounded JSON snapshot without changing ReconForge's core code.
    """

    _registry: ClassVar[dict[str, CurrencySpec]] = {}
    _manifest: ClassVar[CurrencyRegistryManifest | None] = None
    _lock: ClassVar[RLock] = RLock()

    @classmethod
    def _state_payload(
        cls,
        registry: Mapping[str, CurrencySpec],
        *,
        registry_version: str,
        source: str,
        source_url: str,
        published_at: str,
    ) -> dict[str, object]:
        return {
            "currencies": [registry[code].to_dict() for code in sorted(registry)],
            "published_at": published_at,
            "registry_version": registry_version,
            "schema_version": _CURRENCY_REGISTRY_SCHEMA_VERSION,
            "source": source,
            "source_url": source_url,
        }

    @classmethod
    def _build_state(cls, payload: Mapping[str, object]) -> tuple[dict[str, CurrencySpec], CurrencyRegistryManifest]:
        allowed_top_level = {
            "currencies",
            "default_rounding_policy",
            "digest",
            "published_at",
            "registry_version",
            "schema_version",
            "source",
            "source_url",
        }
        unexpected = sorted(set(payload) - allowed_top_level)
        if unexpected:
            raise InvalidAmountError(f"currency registry contains unsupported fields: {', '.join(unexpected)}")

        schema_version = payload.get("schema_version")
        if isinstance(schema_version, bool) or schema_version != _CURRENCY_REGISTRY_SCHEMA_VERSION:
            raise InvalidAmountError(f"currency registry schema_version must be {_CURRENCY_REGISTRY_SCHEMA_VERSION}")
        registry_version = str(payload.get("registry_version") or "").strip()
        if not _REGISTRY_VERSION_PATTERN.fullmatch(registry_version):
            raise InvalidAmountError("currency registry version is missing or invalid")
        source = str(payload.get("source") or "").strip()
        source_url = str(payload.get("source_url") or "").strip()
        published_at = str(payload.get("published_at") or "").strip()
        if not source or len(source) > 500:
            raise InvalidAmountError("currency registry source must contain between 1 and 500 characters")
        if source_url and (not source_url.startswith("https://") or len(source_url) > 2_048):
            raise InvalidAmountError("currency registry source_url must be an HTTPS URL")
        if len(published_at) > 32:
            raise InvalidAmountError("currency registry published_at must not exceed 32 characters")
        default_rounding = str(payload.get("default_rounding_policy") or "ROUND_HALF_UP").strip().upper()
        _rounding_mode(default_rounding)

        raw_currencies = payload.get("currencies")
        if not isinstance(raw_currencies, list) or not 1 <= len(raw_currencies) <= _MAX_CURRENCIES:
            raise InvalidAmountError(f"currency registry must contain between 1 and {_MAX_CURRENCIES} entries")
        registry: dict[str, CurrencySpec] = {}
        allowed_currency_fields = {
            "code",
            "minor_units",
            "name",
            "numeric_code",
            "rounding_policy",
            "symbol",
        }
        for index, raw_spec in enumerate(raw_currencies):
            if not isinstance(raw_spec, Mapping):
                raise InvalidAmountError(f"currency registry entry {index} must be an object")
            unexpected_spec = sorted(set(raw_spec) - allowed_currency_fields)
            if unexpected_spec:
                raise InvalidAmountError(
                    f"currency registry entry {index} contains unsupported fields: {', '.join(unexpected_spec)}"
                )
            try:
                spec = CurrencySpec(
                    code=str(raw_spec.get("code") or ""),
                    name=str(raw_spec.get("name") or ""),
                    minor_units=raw_spec.get("minor_units"),  # type: ignore[arg-type]
                    symbol=str(raw_spec.get("symbol") or ""),
                    numeric_code=str(raw_spec.get("numeric_code") or ""),
                    rounding_policy=str(raw_spec.get("rounding_policy") or default_rounding),
                )
            except InvalidAmountError as exc:
                raise InvalidAmountError(f"currency registry entry {index} is invalid: {exc}") from exc
            if spec.code in registry:
                raise InvalidAmountError(f"currency registry contains duplicate code: {spec.code}")
            registry[spec.code] = spec

        canonical_payload = cls._state_payload(
            registry,
            registry_version=registry_version,
            source=source,
            source_url=source_url,
            published_at=published_at,
        )
        digest = _sha256_payload(canonical_payload)
        expected_digest = str(payload.get("digest") or "").strip().lower()
        if expected_digest and (
            not _SHA256_PATTERN.fullmatch(expected_digest) or not hmac.compare_digest(expected_digest, digest)
        ):
            raise InvalidAmountError("currency registry digest verification failed")
        manifest = CurrencyRegistryManifest(
            schema_version=_CURRENCY_REGISTRY_SCHEMA_VERSION,
            registry_version=registry_version,
            source=source,
            source_url=source_url,
            published_at=published_at,
            digest=digest,
            currency_count=len(registry),
        )
        return registry, manifest

    @classmethod
    def _install_payload(
        cls,
        payload: object,
        *,
        expected_digest: str | None = None,
    ) -> CurrencyRegistryManifest:
        if not isinstance(payload, Mapping):
            raise InvalidAmountError("currency registry root must be a JSON object")
        registry, manifest = cls._build_state(payload)
        if expected_digest is not None:
            normalized_expected = str(expected_digest).strip().lower()
            if not _SHA256_PATTERN.fullmatch(normalized_expected):
                raise InvalidAmountError("expected currency registry digest must be a SHA-256 hex value")
            if not hmac.compare_digest(normalized_expected, manifest.digest):
                raise InvalidAmountError("currency registry does not match the approved expected digest")
        with cls._lock:
            cls._registry = registry
            cls._manifest = manifest
        return manifest

    @classmethod
    def _ensure_defaults(cls) -> None:
        with cls._lock:
            if cls._manifest is not None:
                return
            resource = files("reconforge.data").joinpath(_BUNDLED_CURRENCY_REGISTRY)
            try:
                text = resource.read_text(encoding="utf-8")
            except (FileNotFoundError, OSError) as exc:
                raise InvalidAmountError("bundled currency registry is unavailable") from exc
            payload = _json_without_duplicate_keys(text)
            registry, manifest = cls._build_state(payload if isinstance(payload, Mapping) else {})
            cls._registry = registry
            cls._manifest = manifest

    @classmethod
    def reset_to_bundled(cls) -> CurrencyRegistryManifest:
        """Reload the packaged registry snapshot, primarily for controlled process reset."""

        with cls._lock:
            cls._registry = {}
            cls._manifest = None
        cls._ensure_defaults()
        return cls.manifest()

    @classmethod
    def register(
        cls,
        spec: CurrencySpec,
        *,
        registry_version: str | None = None,
        source: str | None = None,
    ) -> CurrencyRegistryManifest:
        """Explicitly add or replace one policy and publish a new atomic snapshot."""

        cls._ensure_defaults()
        if not isinstance(spec, CurrencySpec):
            raise InvalidAmountError("currency registration requires a CurrencySpec")
        with cls._lock:
            current_manifest = cls._manifest
            if current_manifest is None:
                raise InvalidAmountError("currency registry is unavailable")
            next_registry = dict(cls._registry)
            next_registry[spec.code] = spec
            next_version = registry_version or (
                current_manifest.registry_version
                if current_manifest.registry_version.endswith("+local")
                else f"{current_manifest.registry_version}+local"
            )
            local_source_suffix = "; explicit local runtime registration"
            next_source = source or (
                current_manifest.source
                if current_manifest.source.endswith(local_source_suffix)
                else f"{current_manifest.source}{local_source_suffix}"
            )
            payload = cls._state_payload(
                next_registry,
                registry_version=next_version,
                source=next_source,
                source_url=current_manifest.source_url if source is None else "",
                published_at=current_manifest.published_at,
            )
            registry, manifest = cls._build_state(payload)
            cls._registry = registry
            cls._manifest = manifest
            return manifest

    @classmethod
    def load_file(
        cls,
        path: Path | str,
        *,
        expected_digest: str | None = None,
    ) -> CurrencyRegistryManifest:
        """Atomically replace the registry from one bounded, explicit local JSON file."""

        registry_path = Path(path)
        try:
            if not registry_path.is_file():
                raise InvalidAmountError("currency registry path must identify a regular file")
            size = registry_path.stat().st_size
            if size <= 0 or size > _MAX_CURRENCY_REGISTRY_BYTES:
                raise InvalidAmountError(
                    f"currency registry file must contain between 1 and {_MAX_CURRENCY_REGISTRY_BYTES} bytes"
                )
            text = registry_path.read_text(encoding="utf-8")
        except InvalidAmountError:
            raise
        except (OSError, UnicodeError) as exc:
            raise InvalidAmountError("currency registry file cannot be read safely") from exc
        return cls._install_payload(
            _json_without_duplicate_keys(text),
            expected_digest=expected_digest,
        )

    @classmethod
    def install_snapshot(
        cls,
        payload: Mapping[str, object],
        *,
        expected_digest: str | None = None,
    ) -> CurrencyRegistryManifest:
        """Atomically replace the registry from an already parsed snapshot."""

        return cls._install_payload(payload, expected_digest=expected_digest)

    @classmethod
    def get(cls, code: str) -> CurrencySpec:
        return cls.resolve(code).spec

    @classmethod
    def resolve(cls, code: str) -> ResolvedCurrencyPolicy:
        cls._ensure_defaults()
        clean = str(code).strip().upper()
        if not clean:
            raise InvalidAmountError("currency code cannot be empty")
        if not _CURRENCY_CODE_PATTERN.fullmatch(clean):
            raise InvalidAmountError("currency code must contain exactly three ASCII letters")
        with cls._lock:
            spec = cls._registry.get(clean)
            if spec is None:
                raise UnknownCurrencyError(f"currency code is not registered: {clean}")
            manifest = cls._manifest
            if manifest is None:
                raise InvalidAmountError("currency registry is unavailable")
            return ResolvedCurrencyPolicy(
                spec=spec,
                registry_version=manifest.registry_version,
                registry_digest=manifest.digest,
            )

    @classmethod
    def get_precision(cls, code: str) -> int:
        return cls.get(code).minor_units

    @classmethod
    def contains(cls, code: str) -> bool:
        try:
            cls.get(code)
        except InvalidAmountError:
            return False
        return True

    @classmethod
    def manifest(cls) -> CurrencyRegistryManifest:
        cls._ensure_defaults()
        with cls._lock:
            manifest = cls._manifest
            if manifest is None:
                raise InvalidAmountError("currency registry is unavailable")
            return manifest

    @classmethod
    def snapshot(cls) -> dict[str, object]:
        """Return the complete canonical snapshot plus its verification digest."""

        cls._ensure_defaults()
        with cls._lock:
            manifest = cls._manifest
            if manifest is None:
                raise InvalidAmountError("currency registry is unavailable")
            payload = cls._state_payload(
                cls._registry,
                registry_version=manifest.registry_version,
                source=manifest.source,
                source_url=manifest.source_url,
                published_at=manifest.published_at,
            )
            payload["digest"] = manifest.digest
            return payload


class Money:
    """Canonical representation of an amount bound to an explicit currency."""

    def __init__(
        self,
        amount: object,
        currency: str = "USD",
        *,
        strict_precision: bool = False,
        input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    ) -> None:
        resolution = CurrencyRegistry.resolve(currency)
        self._set_amount(
            amount,
            resolution=resolution,
            strict_precision=strict_precision,
            input_policy=input_policy,
        )
        if input_policy == LEGACY_FINANCIAL_INPUT_POLICY and _is_binary_floating_point(amount):
            _warn_legacy_financial_input_once()

    @classmethod
    def from_exact(
        cls,
        amount: object,
        currency: str = "USD",
        *,
        strict_precision: bool = False,
    ) -> Money:
        """Construct Money under the current strict financial-input policy."""

        return cls(
            amount,
            currency,
            strict_precision=strict_precision,
            input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    def _set_amount(
        self,
        amount: object,
        *,
        resolution: ResolvedCurrencyPolicy,
        strict_precision: bool,
        input_policy: FinancialInputPolicy,
    ) -> None:
        spec = resolution.spec
        self._currency = spec.code
        self._minor_units = spec.minor_units
        self._rounding_policy = spec.rounding_policy
        self._policy_digest = resolution.policy_digest
        self._registry_version = resolution.registry_version
        self._registry_digest = resolution.registry_digest
        if strict_precision:
            self._amount = parse_amount_for_currency_precision(
                amount,
                precision=spec.minor_units,
                rounding_policy=spec.rounding_policy,
                input_policy=input_policy,
                _warn_on_legacy_input=False,
            )
        else:
            parsed = parse_amount(
                amount,
                input_policy=input_policy,
                _warn_on_legacy_input=False,
            )
            self._amount = _quantize_decimal(
                parsed,
                precision=spec.minor_units,
                rounding_policy=spec.rounding_policy,
            )

    @classmethod
    def _from_resolved(
        cls,
        amount: object,
        resolution: ResolvedCurrencyPolicy,
        *,
        strict_precision: bool = False,
    ) -> Money:
        instance = cls.__new__(cls)
        instance._set_amount(
            amount,
            resolution=resolution,
            strict_precision=strict_precision,
            input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
        return instance

    def _resolution(self) -> ResolvedCurrencyPolicy:
        return ResolvedCurrencyPolicy(
            spec=CurrencySpec(
                code=self._currency,
                name=self._currency,
                minor_units=self._minor_units,
                rounding_policy=self._rounding_policy,
            ),
            registry_version=self._registry_version,
            registry_digest=self._registry_digest,
        )

    @property
    def amount(self) -> Decimal:
        return self._amount

    @property
    def currency(self) -> str:
        return self._currency

    @property
    def minor_units(self) -> int:
        return self._minor_units

    @property
    def rounding_policy(self) -> str:
        return self._rounding_policy

    @property
    def currency_policy_digest(self) -> str:
        return self._policy_digest

    @property
    def currency_registry_version(self) -> str:
        return self._registry_version

    @property
    def currency_registry_digest(self) -> str:
        return self._registry_digest

    def to_minor_units(self) -> int:
        factor = Decimal(10) ** self._minor_units
        return int(self._amount * factor)

    @classmethod
    def from_minor_units(cls, minor_units: int, currency: str) -> Money:
        if not isinstance(minor_units, int):
            raise InvalidAmountError("minor_units must be an integer")
        resolution = CurrencyRegistry.resolve(currency)
        factor = Decimal(10) ** resolution.spec.minor_units
        amount = Decimal(minor_units) / factor
        return cls._from_resolved(amount, resolution, strict_precision=True)

    def as_canonical_str(self) -> str:
        return f"{self._amount} {self._currency}"

    def to_dict(self) -> dict[str, str]:
        """Return the backward-compatible amount/currency representation."""

        return {"amount": str(self._amount), "currency": self._currency}

    def to_canonical_dict(self) -> dict[str, object]:
        """Return deterministic value, policy, and registry lineage."""

        return {
            "amount": str(self._amount),
            "currency": self._currency,
            "currency_policy_digest": self._policy_digest,
            "currency_registry_digest": self._registry_digest,
            "currency_registry_version": self._registry_version,
            "minor_units": self._minor_units,
            "rounding_policy": self._rounding_policy,
            "schema_version": 1,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Money:
        if not isinstance(data, dict) or "amount" not in data or "currency" not in data:
            raise InvalidAmountError("dictionary must contain 'amount' and 'currency'")
        return cls(data["amount"], currency=str(data["currency"]))

    @classmethod
    def from_canonical_dict(cls, data: Mapping[str, object]) -> Money:
        """Restore a canonical value only when its embedded financial policy is valid."""

        required = {
            "amount",
            "currency",
            "currency_policy_digest",
            "currency_registry_digest",
            "currency_registry_version",
            "minor_units",
            "rounding_policy",
            "schema_version",
        }
        if not isinstance(data, Mapping) or set(data) != required or data.get("schema_version") != 1:
            raise InvalidAmountError("canonical money dictionary does not match schema_version 1")
        current = CurrencyRegistry.resolve(str(data["currency"]))
        minor_units = data["minor_units"]
        rounding_policy = str(data["rounding_policy"])
        policy_digest = str(data["currency_policy_digest"])
        registry_digest = str(data["currency_registry_digest"])
        registry_version = str(data["currency_registry_version"])
        if (
            isinstance(minor_units, bool)
            or not isinstance(minor_units, int)
            or minor_units != current.spec.minor_units
            or rounding_policy != current.spec.rounding_policy
            or not _SHA256_PATTERN.fullmatch(policy_digest)
            or not hmac.compare_digest(policy_digest, current.policy_digest)
        ):
            raise CurrencyPolicyMismatchError("canonical money currency policy does not match the installed policy")
        if not _SHA256_PATTERN.fullmatch(registry_digest) or not _REGISTRY_VERSION_PATTERN.fullmatch(registry_version):
            raise InvalidAmountError("canonical money registry provenance is invalid")
        historical_resolution = ResolvedCurrencyPolicy(
            spec=current.spec,
            registry_version=registry_version,
            registry_digest=registry_digest,
        )
        return cls._from_resolved(data["amount"], historical_resolution, strict_precision=True)

    def _check_currency(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise CurrencyMismatchError("Operation requires a Money object")
        if self._currency != other._currency:
            raise CurrencyMismatchError(
                f"Cannot perform financial operation between {self._currency} and {other._currency}"
            )
        if self._policy_digest != other._policy_digest:
            raise CurrencyPolicyMismatchError(
                f"Cannot combine {self._currency} values created under different financial policies"
            )

    def __add__(self, other: Money) -> Money:
        self._check_currency(other)
        return self._from_resolved(_exact_add(self._amount, other._amount), self._resolution())

    def __sub__(self, other: Money) -> Money:
        self._check_currency(other)
        return self._from_resolved(
            _exact_add(self._amount, other._amount, subtract=True),
            self._resolution(),
        )

    def __mul__(self, scalar: float | int | str | Decimal) -> Money:
        factor = parse_amount(scalar)
        return self._from_resolved(_exact_multiply(self._amount, factor), self._resolution())

    def __rmul__(self, scalar: float | int | str | Decimal) -> Money:
        return self.__mul__(scalar)

    def multiply_exact(self, scalar: object) -> Money:
        """Multiply by a scalar under the current strict input policy."""

        factor = parse_exact_amount(scalar)
        return self._from_resolved(_exact_multiply(self._amount, factor), self._resolution())

    def __truediv__(self, scalar: float | int | str | Decimal) -> Money:
        factor = parse_amount(scalar)
        if factor == Decimal("0"):
            raise InvalidAmountError("division by zero is not allowed")
        quotient = _divide_for_money(
            self._amount,
            factor,
            precision=self._minor_units,
            rounding_policy=self._rounding_policy,
        )
        return self._from_resolved(quotient, self._resolution(), strict_precision=True)

    def divide_exact(self, scalar: object) -> Money:
        """Divide by a scalar under the current strict input policy."""

        factor = parse_exact_amount(scalar)
        if factor == Decimal("0"):
            raise InvalidAmountError("division by zero is not allowed")
        quotient = _divide_for_money(
            self._amount,
            factor,
            precision=self._minor_units,
            rounding_policy=self._rounding_policy,
        )
        return self._from_resolved(quotient, self._resolution(), strict_precision=True)

    def __neg__(self) -> Money:
        return self._from_resolved(-self._amount, self._resolution())

    def __abs__(self) -> Money:
        return self._from_resolved(abs(self._amount), self._resolution())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return False
        return (
            self._currency == other._currency
            and self._amount == other._amount
            and self._policy_digest == other._policy_digest
        )

    def __lt__(self, other: Money) -> bool:
        self._check_currency(other)
        return self._amount < other._amount

    def __le__(self, other: Money) -> bool:
        self._check_currency(other)
        return self._amount <= other._amount

    def __gt__(self, other: Money) -> bool:
        self._check_currency(other)
        return self._amount > other._amount

    def __ge__(self, other: Money) -> bool:
        self._check_currency(other)
        return self._amount >= other._amount

    def __repr__(self) -> str:
        return f"Money('{self._amount}', '{self._currency}')"

    def __str__(self) -> str:
        return self.as_canonical_str()


@dataclass(frozen=True)
class MinorMoney:
    """Representation of monetary value in minor units (cents/fils)."""

    minor_units: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.minor_units, bool) or not isinstance(self.minor_units, int):
            raise InvalidAmountError("minor_units must be an integer")
        resolution = CurrencyRegistry.resolve(self.currency)
        object.__setattr__(self, "currency", resolution.spec.code)

    def to_money(self) -> Money:
        return Money.from_minor_units(self.minor_units, self.currency)


@dataclass(frozen=True)
class Quantity:
    """Canonical operational quantity with unit and precision scale."""

    value: Decimal
    unit: str = "PCS"
    scale: int = 4

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            parsed = parse_amount(self.value)
            object.__setattr__(self, "value", parsed)
        clean_unit = self.unit.strip().upper()
        if not clean_unit:
            raise InvalidAmountError("unit cannot be empty")
        object.__setattr__(self, "unit", clean_unit)


@dataclass(frozen=True)
class ExchangeRate:
    """Exchange rate binding base_currency to quote_currency with effective date and source lineage."""

    base_currency: str
    quote_currency: str
    rate: Decimal
    source: str = "MANUAL"
    effective_at: str = ""
    _base_policy: ResolvedCurrencyPolicy = field(init=False, repr=False, compare=False)
    _quote_policy: ResolvedCurrencyPolicy = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        base_policy = CurrencyRegistry.resolve(self.base_currency)
        quote_policy = CurrencyRegistry.resolve(self.quote_currency)
        parsed_rate = parse_amount(self.rate)
        if parsed_rate <= Decimal("0"):
            raise InvalidAmountError("exchange rate must be greater than zero")
        if base_policy.spec.code == quote_policy.spec.code and parsed_rate != Decimal("1"):
            raise InvalidAmountError("same currency exchange rate must be 1")
        source = str(self.source).strip()
        if not source:
            raise InvalidAmountError("exchange rate source cannot be empty")
        object.__setattr__(self, "base_currency", base_policy.spec.code)
        object.__setattr__(self, "quote_currency", quote_policy.spec.code)
        object.__setattr__(self, "rate", parsed_rate)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "_base_policy", base_policy)
        object.__setattr__(self, "_quote_policy", quote_policy)

    def convert(self, money: Money) -> Money:
        if not isinstance(money, Money):
            raise InvalidAmountError("money must be a Money object")
        if money.currency != self.base_currency:
            raise CurrencyMismatchError(
                f"Exchange rate base currency ({self.base_currency}) does not match money currency ({money.currency})"
            )
        if money.currency_policy_digest != self._base_policy.policy_digest:
            raise CurrencyPolicyMismatchError(
                f"Exchange rate base policy does not match the {self.base_currency} Money policy"
            )
        converted_amount = _exact_multiply(money.amount, self.rate)
        return Money._from_resolved(converted_amount, self._quote_policy)
