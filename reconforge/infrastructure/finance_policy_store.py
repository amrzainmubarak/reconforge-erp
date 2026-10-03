"""Backend adapters for the retained Finance Core currency policy."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_policy import (
    POLICY_COLUMNS,
    FinanceCurrencyPolicy,
    FinancePolicyError,
    verified_registry_context,
)
from reconforge.domain.models import utc_now_text
from reconforge.utils.money import CurrencyRegistryContext, InvalidAmountError


class FinancePolicyStore:
    """Use the caller's existing transaction and tenant/workspace scope."""

    def __init__(self, connection: Any, *, tenant_id: str | None = None) -> None:
        self.connection = connection
        self.tenant_id = tenant_id

    @staticmethod
    def _row(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
        if isinstance(row, Mapping) or hasattr(row, "keys"):
            return {key: row[key] for key in columns}
        return dict(zip(columns, row, strict=True))

    def _snapshot(self, digest: str) -> CurrencyRegistryContext:
        if self.tenant_id is None:
            row = self.connection.execute(
                "SELECT snapshot_json FROM currency_registry_snapshots WHERE registry_digest = ?", (digest,)
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT snapshot_json FROM reconforge.currency_registry_snapshots WHERE tenant_id=%s AND registry_digest=%s",
                (self.tenant_id, digest),
            ).fetchone()
        payload = None if row is None else self._row(row, ("snapshot_json",))["snapshot_json"]
        context = verified_registry_context(payload)
        if context.registry_manifest.digest != digest:
            raise FinancePolicyError("finance_currency_policy_invalid: snapshot digest does not match its identity.")
        return context

    def entry(self, record: Mapping[str, object]) -> tuple[FinanceCurrencyPolicy, CurrencyRegistryContext]:
        try:
            if any(record.get(column) is None for column in POLICY_COLUMNS):
                raise FinancePolicyError(
                    "finance_currency_policy_unverified: legacy entry retains raw minor units but has no "
                    "verified monetary policy; obtain independently reviewed historical policy evidence "
                    "before interpreting or changing this entry."
                )
            context = self._snapshot(str(record["currency_registry_digest"]))
            return FinanceCurrencyPolicy.verify_record(record, context), context
        except (FinancePolicyError, InvalidAmountError) as exc:
            from reconforge.platform.common import PlatformError

            raise PlatformError(str(exc)) from exc

    def capture(
        self, *, workspace_id: str, currency_code: str, minor_units: int, actor_label: str,
        existing: Mapping[str, object] | None = None,
    ) -> tuple[FinanceCurrencyPolicy, CurrencyRegistryContext]:
        try:
            if existing is not None:
                policy, context = self.entry(existing)
                if policy.currency_code != currency_code:
                    raise FinancePolicyError("finance_currency_policy_mismatch: draft currency policy is immutable.")
            else:
                if self.tenant_id is None:
                    row = self.connection.execute(
                        "SELECT registry_version,registry_digest FROM currency_registry_bindings WHERE workspace_id=?",
                        (workspace_id,),
                    ).fetchone()
                else:
                    row = self.connection.execute(
                        "SELECT registry_version,registry_digest FROM reconforge.currency_registry_bindings "
                        "WHERE tenant_id=%s AND workspace_id=%s FOR SHARE",
                        (self.tenant_id, workspace_id),
                    ).fetchone()
                if row is None:
                    context = CurrencyRegistryContext.from_installed()
                else:
                    binding = self._row(row, ("registry_version", "registry_digest"))
                    context = self._snapshot(str(binding["registry_digest"]))
                    if context.registry_manifest.registry_version != binding["registry_version"]:
                        raise FinancePolicyError("finance_currency_policy_invalid: workspace binding version mismatch.")
                policy = FinanceCurrencyPolicy.capture(currency_code, context)
            if policy.precision != minor_units:
                raise FinancePolicyError(
                    "finance_currency_policy_mismatch: currency master precision differs from the captured policy."
                )
            payload = json.dumps(context.snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if self.tenant_id is None:
                self.connection.execute(
                    "INSERT INTO currency_registry_snapshots "
                    "(registry_digest,registry_version,snapshot_json,captured_at,captured_by) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(registry_digest) DO NOTHING",
                    (policy.registry_digest, policy.registry_version, payload, utc_now_text(), actor_label),
                )
            else:
                self.connection.execute(
                    "INSERT INTO reconforge.currency_registry_snapshots "
                    "(tenant_id,registry_digest,registry_version,snapshot_json,captured_by) VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT(tenant_id,registry_digest) DO NOTHING",
                    (self.tenant_id, policy.registry_digest, policy.registry_version, payload, actor_label),
                )
            self._snapshot(policy.registry_digest)
            return policy, context
        except (FinancePolicyError, InvalidAmountError) as exc:
            from reconforge.platform.common import PlatformError

            raise PlatformError(str(exc)) from exc
