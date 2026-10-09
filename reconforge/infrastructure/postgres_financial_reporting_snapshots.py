"""Durable native-evidence report capture and bounded keyset drill-down."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from reconforge.domain.finance_balances import balance_window
from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text
from reconforge.domain.financial_reporting import ReportingScope, fail
from reconforge.domain.financial_reporting_stream import (
    EVIDENCE_CHAIN_SEED,
    MAX_EVIDENCE_PAGE,
    StreamingFinancialReport,
)
from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.utils.time import utc_now_text


class PostgresFinancialReportSnapshots:
    def __init__(self, owner: PostgresFinancialReportingRepository) -> None:
        self.owner = owner
        self.connection, self.tenant_id = owner.connection, owner.tenant_id

    def _capture(self, identifier: str, actor: PostingActor) -> dict[str, Any]:
        rows = records(self.connection.execute(
            "SELECT * FROM reconforge.financial_report_captures WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, text(identifier, "snapshot_id")),
        ))
        if not rows:
            fail("Report snapshot is absent or outside current scope.", "financial_reporting_not_found")
        capture = rows[0]
        self.owner._actor(actor, "finance_core.read", capture, mutation=False)
        return capture

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            capture = self._capture(identifier, actor)
            rows = records(self.connection.execute(
                "SELECT payload,report_digest FROM reconforge.financial_report_snapshots WHERE tenant_id=%s AND capture_id=%s",
                (self.tenant_id, capture["id"]),
            ))
            if not rows or rows[0]["report_digest"] != digest_payload({key: value for key, value in rows[0]["payload"].items() if key != "report_digest"}):
                fail("Report summary differs from its retained exact digest.", "financial_reporting_integrity_invalid")
            result: dict[str, Any] = rows[0]["payload"]
            if result["report_digest"] != rows[0]["report_digest"] or any(result[key] != capture[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
                fail("Report summary differs from its captured authority.", "financial_reporting_integrity_invalid")
            return result

    def create(self, *, map_id: str, period_id: str, as_of_date: str, organization_code: str,
               entity_code: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"actor_id": actor.user_id, "map_id": text(map_id, "map_id"),
                   "period_id": text(period_id, "period_id"), "as_of_date": as_of_date}
        digest = digest_payload(request)
        text(command_id, "command_id", maximum=140)
        with self.owner._transaction(write=True):
            mapping = self.owner._map(map_id)
            self.owner._actor(actor, "finance_core.read", mapping, mutation=False)
            if mapping["status"] != "Reviewed":
                fail("Snapshots require an independently reviewed classification map.")
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                    (canonical_json([self.tenant_id, mapping["workspace_id"], "financial-report-snapshot", command_id]),))
            replay = records(self.connection.execute(
                "SELECT id,request_digest,request_json FROM reconforge.financial_report_captures WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                (self.tenant_id, mapping["workspace_id"], command_id),
            ))
            if replay:
                if replay[0]["request_digest"] != digest or replay[0]["request_json"] != request:
                    fail("Snapshot command already binds a different exact request or actor.", "financial_reporting_command_conflict")
                return self.get(replay[0]["id"], actor=actor)
            periods = records(self.connection.execute(
                "SELECT start_date::text,end_date::text FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s FOR SHARE",
                (self.tenant_id, period_id, mapping["workspace_id"]),
            ))
            if not periods:
                fail("Report period is absent or outside current workspace.", "financial_reporting_scope_denied")
            start, end, cutoff = balance_window(periods[0]["start_date"], periods[0]["end_date"], as_of_date)
            identifier = "FRS1-" + digest_payload([self.tenant_id, mapping["workspace_id"], command_id])[:32]
            self.connection.execute(
                """INSERT INTO reconforge.financial_report_captures(tenant_id,id,workspace_id,organization_id,legal_entity_id,map_id,period_id,as_of_date,actor_id,command_id,request_digest,request_json,source_snapshot,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'',%s)""",
                (self.tenant_id, identifier, mapping["workspace_id"], mapping["organization_id"], mapping["legal_entity_id"],
                 map_id, period_id, cutoff, actor.user_id, command_id, digest, canonical_json(request), utc_now_text()),
            )
            capture = self._capture(identifier, actor)
            metadata = {"id": identifier, **{key: mapping[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                        "organization_code": organization_code, "entity_code": entity_code, "period_id": period_id,
                        "period_start": start, "period_end": end, "as_of_date": cutoff,
                        "source_snapshot": capture["source_snapshot"], "captured_at": capture["created_at"]}
            fold = StreamingFinancialReport(mapping, metadata)
            with self.connection.cursor(name="report_" + uuid4().hex) as cursor:
                cursor.execute("SELECT effect_id,ordinal,previous_digest,chain_digest FROM reconforge.financial_report_members WHERE tenant_id=%s AND capture_id=%s ORDER BY ordinal", (self.tenant_id, identifier))
                while batch := cursor.fetchmany(100):
                    members = [dict(row) for row in batch]
                    effects = self.owner.posting.get_effects_batch([row["effect_id"] for row in members], actor=actor)
                    for member, effect in zip(members, effects, strict=True):
                        ordinal, previous, chain = fold.consume(effect)
                        if (ordinal, previous, chain) != (member["ordinal"], member["previous_digest"], member["chain_digest"]):
                            fail("Report stream differs from its durable captured evidence chain.", "financial_reporting_integrity_invalid")
            summary = fold.finish()
            self.owner._actor(actor, "finance_core.read", mapping, mutation=False)
            audit, outbox = self.owner._event(summary, "financial_report_snapshot_created", actor,
                                             {"report_digest": summary["report_digest"], "evidence_digest": summary["evidence_digest"]})
            self.connection.execute(
                "INSERT INTO reconforge.financial_report_snapshots(tenant_id,capture_id,payload,report_digest,audit_event_id,outbox_event_id) VALUES(%s,%s,%s::jsonb,%s,%s,%s)",
                (self.tenant_id, identifier, canonical_json(summary), summary["report_digest"], audit, outbox),
            )
            return summary

    def list(self, scope: ReportingScope, *, actor: PostingActor, after_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 50:
            fail("Snapshot list requires a page of one to fifty records.")
        with self.owner._transaction():
            self.owner._actor(actor, "finance_core.read", scope.payload(), mutation=False)
            rows = records(self.connection.execute(
                """SELECT c.id,c.map_id,c.period_id,c.as_of_date::text,c.created_at AS captured_at,
                (s.payload->>'effect_count')::bigint AS effect_count,(s.payload->>'line_count')::bigint AS line_count,s.report_digest
                FROM reconforge.financial_report_captures c JOIN reconforge.financial_report_snapshots s
                ON s.tenant_id=c.tenant_id AND s.capture_id=c.id
                WHERE c.tenant_id=%s AND c.workspace_id=%s AND c.organization_id=%s AND c.legal_entity_id=%s
                AND c.id COLLATE "C">%s ORDER BY c.id COLLATE "C" LIMIT %s""",
                (self.tenant_id, scope.workspace_id, scope.organization_id, scope.legal_entity_id, after_id, limit),
            ))
            return rows

    def evidence(self, identifier: str, *, expected_digest: str, actor: PostingActor, after: int = 0,
                 limit: int = 20) -> dict[str, Any]:
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= MAX_EVIDENCE_PAGE:
            fail("Evidence requires a nonnegative keyset cursor and bounded positive page size.")
        with self.owner._transaction():
            summary = self.get(identifier, actor=actor)
            if summary["report_digest"] != expected_digest:
                fail("Evidence cursor belongs to another retained report digest.", "financial_reporting_cursor_conflict")
            if after > summary["effect_count"]:
                fail("Evidence cursor exceeds the captured source set.", "financial_reporting_cursor_conflict")
            rows = records(self.connection.execute(
                "SELECT * FROM reconforge.financial_report_members WHERE tenant_id=%s AND capture_id=%s AND ordinal>%s ORDER BY ordinal LIMIT %s",
                (self.tenant_id, identifier, after, limit),
            ))
            items: list[dict[str, Any]] = []
            used = 0
            for row in rows:
                effect = self.owner.posting.get_effect(row["effect_id"], actor=actor)
                item = {key: row[key] for key in ("ordinal", "effect_id", "validation_digest", "previous_digest", "chain_digest")}
                item["effect"] = effect
                size = len(canonical_json(item).encode("utf-8"))
                if items and used + size > 4 * 1024 * 1024:
                    break
                used += size
                items.append(item)
            last = items[-1]["ordinal"] if items else after
            previous = items[0]["previous_digest"] if items else summary["evidence_digest"] if after else EVIDENCE_CHAIN_SEED
            return {"snapshot_id": identifier, "report_digest": summary["report_digest"], "evidence_digest": summary["evidence_digest"],
                    "after": after, "previous_digest": previous, "items": items, "next_after": last if last < summary["effect_count"] else None,
                    "effect_count": summary["effect_count"], "page_bytes": used}
