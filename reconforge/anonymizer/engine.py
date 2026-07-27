"""Directory anonymization engine."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import pandas as pd

from reconforge.anonymizer.mapping import (
    AMOUNT_FACTOR_SCALE,
    AMOUNT_NOISE_ALGORITHM_VERSION,
    AnonymizationMap,
    LegacyAmountNoiseInput,
    parse_amount_noise_percent,
)
from reconforge.anonymizer.maskers import mask_frame
from reconforge.io.readers import normalize_columns, read_table
from reconforge.io.writers import canonical_decimal_text, exact_json_dumps
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    validate_financial_input_policy,
)

ANONYMIZATION_MANIFEST_SCHEMA_VERSION = 2
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PRIVACY_BOUNDARY = (
    "Risk-reduction aid only: review every output before sharing; amount noise is deterministic and reversible, "
    "and free-text or unclassified fields may remain sensitive."
)
_MANIFEST_POLICY_FIELDS_V1 = (
    "algorithm_version",
    "prng",
    "profile",
    "mask_amounts",
    "amount_noise_percent",
    "amount_factor_scale",
    "amount_factor_scope",
    "amount_rounding",
    "preserve_dates",
    "date_shift_days",
    "seed_fingerprint",
)
_MANIFEST_POLICY_FIELDS_V2 = (*_MANIFEST_POLICY_FIELDS_V1, "financial_input_policy")


def _is_within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def _sha256_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_anonymization_manifest(
    payload: Mapping[str, object],
    *,
    output_dir: Path | str | None = None,
) -> None:
    """Verify the supported manifest version and its policy/manifest digests."""

    schema_version = payload.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in {1, ANONYMIZATION_MANIFEST_SCHEMA_VERSION}
    ):
        raise ValueError(f"unsupported anonymization manifest schema_version: {schema_version}")
    if payload.get("policy_digest_algorithm") != "sha256" or payload.get("manifest_digest_algorithm") != "sha256":
        raise ValueError("unsupported anonymization manifest digest algorithm")
    policy_fields = (
        _MANIFEST_POLICY_FIELDS_V1
        if schema_version == 1
        else _MANIFEST_POLICY_FIELDS_V2
    )
    if any(field not in payload for field in policy_fields):
        raise ValueError("anonymization manifest policy fields are incomplete")
    financial_input_policy: FinancialInputPolicy
    if schema_version == 1:
        financial_input_policy = LEGACY_FINANCIAL_INPUT_POLICY
    else:
        financial_input_policy = validate_financial_input_policy(
            payload.get("financial_input_policy")
        )
    expected_policy = {
        "algorithm_version": AMOUNT_NOISE_ALGORITHM_VERSION,
        "prng": "python-random-mt19937-randint",
        "amount_factor_scale": AMOUNT_FACTOR_SCALE,
        "amount_factor_scope": "all-amount-columns",
        "amount_rounding": "ROUND_HALF_UP_SOURCE_SCALE",
    }
    for field, expected in expected_policy.items():
        if payload.get(field) != expected:
            raise ValueError(f"unsupported anonymization manifest {field}")
    if payload.get("profile") not in {"consulting-safe", "public-demo"}:
        raise ValueError("unsupported anonymization manifest profile")
    raw_percent = payload.get("amount_noise_percent")
    if not isinstance(raw_percent, str):
        raise ValueError("anonymization manifest amount_noise_percent must be canonical decimal text")
    parsed_percent = parse_amount_noise_percent(
        raw_percent,
        input_policy=financial_input_policy,
    )
    if raw_percent != canonical_decimal_text(parsed_percent):
        raise ValueError("anonymization manifest amount_noise_percent is not canonical")
    if not isinstance(payload.get("mask_amounts"), bool) or not isinstance(payload.get("preserve_dates"), bool):
        raise ValueError("anonymization manifest boolean policy fields are invalid")
    date_shift_days = payload.get("date_shift_days")
    if not isinstance(date_shift_days, int) or isinstance(date_shift_days, bool):
        raise ValueError("anonymization manifest date_shift_days is invalid")
    seed_fingerprint = payload.get("seed_fingerprint")
    if not isinstance(seed_fingerprint, str) or not _SHA256_PATTERN.fullmatch(seed_fingerprint):
        raise ValueError("anonymization manifest seed_fingerprint is invalid")
    source_files = payload.get("source_files")
    if not isinstance(source_files, list) or not source_files or any(
        not isinstance(item, str) or not item for item in source_files
    ):
        raise ValueError("anonymization manifest source_files are invalid")
    if not isinstance(payload.get("private_mapping_exported"), bool):
        raise ValueError("anonymization manifest private_mapping_exported is invalid")
    outputs = payload.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("anonymization manifest outputs are invalid")
    output_names: set[str] = set()
    for item in outputs:
        if not isinstance(item, Mapping):
            raise ValueError("anonymization manifest output entry is invalid")
        name = item.get("name")
        byte_count = item.get("bytes")
        digest = item.get("sha256")
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name in output_names
            or not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 0
            or not isinstance(digest, str)
            or not _SHA256_PATTERN.fullmatch(digest)
        ):
            raise ValueError("anonymization manifest output entry is invalid")
        output_names.add(name)
    if payload.get("privacy_boundary") != _PRIVACY_BOUNDARY:
        raise ValueError("unsupported anonymization manifest privacy boundary")
    policy = {field: payload[field] for field in policy_fields}
    if payload.get("policy_digest") != _sha256_payload(policy):
        raise ValueError("anonymization manifest policy digest does not match")
    manifest_without_digest = dict(payload)
    manifest_without_digest.pop("manifest_digest", None)
    if payload.get("manifest_digest") != _sha256_payload(manifest_without_digest):
        raise ValueError("anonymization manifest digest does not match")
    if output_dir is not None:
        base = Path(output_dir)
        if not base.exists() or not base.is_dir():
            raise ValueError(f"anonymized output directory not found: {base}")
        for item in outputs:
            if not isinstance(item, Mapping):
                raise ValueError("anonymization manifest output entry is invalid")
            path = base / str(item["name"])
            if not path.is_file() or path.stat().st_size != item["bytes"] or _file_sha256(path) != item["sha256"]:
                raise ValueError(f"anonymized output verification failed: {item['name']}")


def _validate_paths(
    source: Path,
    target: Path,
    private_mapping_path: Path | None,
) -> tuple[list[Path], Path | None]:
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Anonymization input directory not found: {source}")
    source_resolved = source.resolve()
    target_resolved = target.resolve()
    if _is_within(target_resolved, source_resolved):
        raise ValueError("anonymized output must be outside the input directory")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("anonymized output directory must be empty or not exist")
    input_files = sorted(path for path in source.glob("*.csv") if path.is_file())
    if not input_files:
        raise ValueError(f"No CSV files found in anonymization input directory: {source}")

    private_resolved: Path | None = None
    if private_mapping_path is not None:
        private_resolved = private_mapping_path.resolve()
        if _is_within(private_resolved, target_resolved):
            raise ValueError("private mapping output must be outside the anonymized output directory")
        if _is_within(private_resolved, source_resolved):
            raise ValueError("private mapping output must be outside the input directory")
        if private_mapping_path.exists():
            raise ValueError(f"private mapping output already exists: {private_mapping_path}")
    return input_files, private_resolved


def _manifest_payload(
    *,
    profile: str,
    seed: int,
    mask_amounts: bool,
    amount_noise_percent: Decimal,
    preserve_dates: bool,
    date_shift_days: int,
    source_files: list[Path],
    output_files: list[Path],
    private_mapping_exported: bool,
    financial_input_policy: FinancialInputPolicy,
) -> dict[str, object]:
    policy: dict[str, object] = {
        "algorithm_version": AMOUNT_NOISE_ALGORITHM_VERSION,
        "prng": "python-random-mt19937-randint",
        "profile": profile,
        "mask_amounts": mask_amounts,
        "amount_noise_percent": canonical_decimal_text(amount_noise_percent),
        "amount_factor_scale": AMOUNT_FACTOR_SCALE,
        "amount_factor_scope": "all-amount-columns",
        "amount_rounding": "ROUND_HALF_UP_SOURCE_SCALE",
        "preserve_dates": preserve_dates,
        "date_shift_days": date_shift_days,
        "seed_fingerprint": hashlib.sha256(str(seed).encode("utf-8")).hexdigest(),
        "financial_input_policy": financial_input_policy,
    }
    payload: dict[str, object] = {
        "schema_version": ANONYMIZATION_MANIFEST_SCHEMA_VERSION,
        **policy,
        "policy_digest_algorithm": "sha256",
        "policy_digest": _sha256_payload(policy),
        "source_files": [path.name for path in source_files],
        "outputs": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": _file_sha256(path)}
            for path in output_files
        ],
        "private_mapping_exported": private_mapping_exported,
        "privacy_boundary": _PRIVACY_BOUNDARY,
    }
    payload["manifest_digest_algorithm"] = "sha256"
    payload["manifest_digest"] = _sha256_payload(payload)
    return payload


def anonymize_directory(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    mask_amounts: bool = False,
    amount_noise_percent: LegacyAmountNoiseInput = Decimal("15"),
    seed: int = 42,
    preserve_dates: bool = False,
    date_shift_days: int = 0,
    profile: str = "consulting-safe",
    private_mapping_path: Path | str | None = None,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> list[Path]:
    """Anonymize CSV exports while preserving referential integrity."""

    source = Path(input_dir)
    target = Path(output_dir)
    private_path = Path(private_mapping_path) if private_mapping_path is not None else None
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("anonymization seed must be an integer")
    financial_input_policy = validate_financial_input_policy(financial_input_policy)
    noise_percent = parse_amount_noise_percent(
        amount_noise_percent,
        input_policy=financial_input_policy,
    )
    if profile == "public-demo":
        mask_amounts = True
        preserve_dates = False
        date_shift_days = date_shift_days or 30
    elif profile == "consulting-safe":
        preserve_dates = preserve_dates
    elif profile not in {"consulting-safe", "public-demo"}:
        raise ValueError("profile must be one of: consulting-safe, public-demo")
    input_files, _ = _validate_paths(source, target, private_path)
    target.mkdir(parents=True, exist_ok=True)
    mapping = AnonymizationMap(seed=seed)
    outputs: list[Path] = []
    for path in input_files:
        frame = normalize_columns(read_table(path))
        masked = mask_frame(
            frame,
            mapping,
            mask_amounts=mask_amounts,
            amount_noise_percent=noise_percent,
            financial_input_policy=financial_input_policy,
            preserve_dates=preserve_dates,
            date_shift_days=date_shift_days,
        )
        output_path = target / path.name
        masked.to_csv(output_path, index=False, lineterminator="\n")
        outputs.append(output_path)
    private_mapping_exported = private_path is not None
    if private_path is not None:
        private_path.parent.mkdir(parents=True, exist_ok=True)
        mapping_frame = pd.DataFrame(
            [
                {"group": group, "original": original, "masked": masked_value}
                for (group, original), masked_value in mapping.values.items()
            ],
            columns=["group", "original", "masked"],
        )
        mapping_frame.to_csv(private_path, index=False, lineterminator="\n")
    manifest_path = target / "anonymization_manifest.json"
    manifest_path.write_text(
        exact_json_dumps(
            _manifest_payload(
                profile=profile,
                seed=seed,
                mask_amounts=mask_amounts,
                amount_noise_percent=noise_percent,
                preserve_dates=preserve_dates,
                date_shift_days=date_shift_days,
                source_files=input_files,
                output_files=outputs,
                private_mapping_exported=private_mapping_exported,
                financial_input_policy=financial_input_policy,
            ),
        ),
        encoding="utf-8",
    )
    outputs.append(manifest_path)
    if private_path is not None:
        outputs.append(private_path)
    return outputs
