import type { ProcurementCommitment } from "../procurement-commitment-data";
export function commitment(): ProcurementCommitment {
  return { id: "order", order_id: "order", number: "BPC1-TEST", workspace_id: "work", organization_id: "org", legal_entity_id: "entity", currency_code: "USD", budget_id: "budget", commitment_id: "commitment",
    preparer_actor_id: "maker", original_minor: "17000", reserved_minor: "17000", consumed_minor: "0", released_minor: "0",
    remaining_minor: "17000", budget_version: 4, status: "Reserved", evidence: { budget_event_id: "reserve-event", audit_event_id: "reserve-audit", outbox_event_id: "reserve-outbox", request_digest: "a".repeat(64) } };
}
