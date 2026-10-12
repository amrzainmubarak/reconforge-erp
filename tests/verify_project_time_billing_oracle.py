"""Independent standard-library project-minute price oracle; no app imports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def integer(value: Any, *, positive: bool = False, maximum: int = 4_500_000_000_000_000_000) -> int:
    if type(value) is str:
        require(re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is not None, "Canonical minor-unit string required")
        value = int(value)
    require(
        type(value) is int and (1 if positive else 0) <= value <= maximum, "Exact bounded nonboolean integer required"
    )
    return value


def normalize(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            name: normalize(item, "amount_minor" if key == "project_minor" else name) for name, item in value.items()
        }
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return integer(value) if key.endswith("_minor") else value


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def day(value: Any) -> str:
    require(type(value) is str and date.fromisoformat(value).isoformat() == value, "Canonical business date required")
    return value


def verify(evidence: dict[str, Any]) -> dict[str, Any]:
    evidence = normalize(evidence)
    require(evidence["schema_version"] == "project-billing-allocation-evidence-v1", "Unknown project billing evidence")
    scope = evidence["scope"]
    require(
        type(evidence["currency_code"]) is str and re.fullmatch(r"[A-Z]{3}", evidence["currency_code"]) is not None,
        "Canonical explicit currency required",
    )
    require(
        type(evidence["customer_code"]) is str
        and re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", evidence["customer_code"]) is not None,
        "Canonical customer required",
    )
    require(
        set(scope) == {"tenant_id", "workspace_id", "organization_id", "legal_entity_id"}
        and all(type(value) is str and value for value in scope.values()),
        "Original qualified scope required",
    )
    prices = evidence["prices"]
    times = evidence["times"]
    registry = evidence["registry_snapshot"]
    require(
        set(registry)
        == {"currencies", "published_at", "registry_version", "schema_version", "source", "source_url", "digest"}
        and type(registry["schema_version"]) is int and registry["schema_version"] == 1,
        "Closed original registry snapshot required",
    )
    require(
        registry["digest"] == digest({key: value for key, value in registry.items() if key != "digest"}),
        "Original registry digest differs",
    )
    currencies = registry["currencies"]
    require(type(currencies) is list and 1 <= len(currencies) <= 1000, "Bounded registry currencies required")
    codes = [row["code"] for row in currencies]
    require(
        codes == sorted(codes) and len(set(codes)) == len(codes), "Original registry currencies duplicate or unordered"
    )
    matches = [row for row in currencies if row["code"] == evidence["currency_code"]]
    require(
        len(matches) == 1 and matches[0]["rounding_policy"] == "ROUND_HALF_UP",
        "Supported captured native currency rounding required",
    )
    precision = integer(matches[0]["minor_units"], maximum=8)
    monetary_policy = {
        "currency_code": evidence["currency_code"],
        "currency_precision": precision,
        "currency_rounding_policy": matches[0]["rounding_policy"],
        "currency_registry_version": registry["registry_version"],
        "currency_registry_digest": registry["digest"],
    }
    require(
        type(prices) is list and 1 <= len(prices) <= 999 and type(times) is list and 1 <= len(times) <= 1000,
        "Bounded source population required",
    )
    price_ids = set()
    for price in prices:
        require(
            price["id"] not in price_ids and all(price[key] == value for key, value in scope.items()),
            "Duplicate or foreign price",
        )
        require(
            price["customer_code"] == evidence["customer_code"] and price["currency_code"] == evidence["currency_code"],
            "Foreign customer/currency",
        )
        require(
            price["approver_id"] and price["preparer_id"] and price["approver_id"] != price["preparer_id"],
            "Independent price approval required",
        )
        integer(price["hourly_price_minor"], positive=True)
        require(price["monetary_policy"] == monetary_policy, "Price captured native policy differs")
        require(day(price["valid_from"]) <= day(price["valid_through"]), "Canonical ordered price dates required")
        for other in prices:
            if other is not price and other["project_id"] == price["project_id"]:
                require(
                    not (
                        price["valid_from"] <= other["valid_through"] and other["valid_from"] <= price["valid_through"]
                    ),
                    "Effective project price versions overlap",
                )
        require(price["source_digest"] == digest(price["source_json"]), "Price source seal differs")
        require(
            all(
                price["source_json"][key] == price[key]
                for key in (
                    *scope,
                    "id",
                    "customer_code",
                    "currency_code",
                    "project_id",
                    "hourly_price_minor",
                    "valid_from",
                    "valid_through",
                    "preparer_id",
                    "dimension_id",
                    "value_id",
                    "monetary_policy",
                )
            ),
            "Price projection differs",
        )
        price_ids.add(price["id"])
    amounts: dict[str, Fraction] = {}
    minutes: dict[str, int] = {}
    time_ids = set()
    employee_days = set()
    selected_prices = set()
    sources = []
    for source in sorted(times, key=lambda row: row["id"]):
        require(
            source["id"] not in time_ids and all(source[key] == value for key, value in scope.items()),
            "Duplicate or foreign whole approved time",
        )
        require(
            source["approver_id"] and source["approver_id"] != source["submitter_id"],
            "Independent time approval required",
        )
        require(
            source["source_digest"] == digest({**source["request_json"], "employment_id": source["employment_id"]}),
            "Original time seal differs",
        )
        require(
            all(source[key] == source["request_json"][key] for key in ("employee_id", "business_date", "lines")),
            "Time projection differs",
        )
        qualified_day = (source["employee_id"], source["business_date"])
        day(source["business_date"])
        require(qualified_day not in employee_days, "Duplicate employee business date")
        employee_days.add(qualified_day)
        time_ids.add(source["id"])
        require(type(source["lines"]) is list and 1 <= len(source["lines"]) <= 128, "Bounded time intervals required")
        previous = -1
        for line in sorted(source["lines"], key=lambda row: row["start_minute"]):
            start = integer(line["start_minute"], maximum=1439)
            end = integer(line["end_minute"], positive=True, maximum=1440)
            require(previous <= start < end, "Positive nonoverlapping original minute interval required")
            previous = end
            candidates = [
                price
                for price in prices
                if price["project_id"] == line["project_id"]
                and price["valid_from"] <= source["business_date"] <= price["valid_through"]
            ]
            require(len(candidates) == 1, "One effective approved project price required")
            price = candidates[0]
            selected_prices.add(price["id"])
            interval = end - start
            project = line["project_id"]
            amounts[project] = amounts.get(project, Fraction()) + Fraction(price["hourly_price_minor"] * interval, 60)
            minutes[project] = minutes.get(project, 0) + interval
            sources.append(
                {
                    "time_id": source["id"],
                    "time_digest": source["source_digest"],
                    "project_id": project,
                    "start_minute": start,
                    "end_minute": end,
                    "minutes": interval,
                    "price_id": price["id"],
                    "price_digest": price["source_digest"],
                    "hourly_price_minor": price["hourly_price_minor"],
                }
            )
    require(selected_prices == price_ids, "Unused price version supplied")
    result = {}
    for project, exact in sorted(amounts.items()):
        whole, remainder = divmod(exact.numerator, exact.denominator)
        amount = whole + int(remainder * 2 >= exact.denominator)
        result[project] = integer(amount, positive=True)
    total = integer(sum(result.values()), positive=True)
    expected = {
        "contract_version": "project-time-billing-v1",
        "rounding": "captured-currency-per-project-v1",
        "currency_code": evidence["currency_code"],
        "monetary_policy": monetary_policy,
        "time_ids": sorted(time_ids),
        "price_ids": sorted(selected_prices),
        "sources": sources,
        "project_minutes": dict(sorted(minutes.items())),
        "project_minor": result,
        "amount_minor": total,
        "ar_lines": [
            {
                "project_id": project,
                "quantity": "1",
                "unit_price_minor": amount,
                "line_total_minor": amount,
                "tax_minor": 0,
            }
            for project, amount in result.items()
        ],
    }
    require(evidence["calculation"] == expected, "Independent exact project allocation differs")
    return {
        "schema_version": "project-billing-independent-allocation-v1",
        "accepted_calculation": True,
        "amount_minor": total,
        "project_minor": result,
        "whole_time_entries": len(time_ids),
        "native_ar_gl_proven": False,
        "country_tax_supported": 0,
        "performance_comparison_accepted": False,
    }


def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in values:
        require(key not in result, "Duplicate JSON member")
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-evidence-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.evidence.open("rb") as stream:
        raw = stream.read(16_777_217)
    require(
        len(raw) <= 16_777_216 and hashlib.sha256(raw).hexdigest() == args.expected_evidence_sha256,
        "Original evidence trusted raw anchor differs",
    )

    def refuse(value: str) -> Any:
        raise ValueError("Noninteger JSON number refused")

    result = verify(json.loads(raw, object_pairs_hook=pairs, parse_float=refuse, parse_constant=refuse))
    result.update(raw_evidence_sha256=hashlib.sha256(raw).hexdigest(), raw_export_anchor=True)
    args.output.write_text(canonical(result) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
