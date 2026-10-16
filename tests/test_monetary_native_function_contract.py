"""Emitted PL/pgSQL binding checks for native monetary owner callbacks.

PostgreSQL compiles table queries lazily. Installing a trigger therefore does
not exercise the binding of qualified local variables in its first callback.
"""

import hashlib
import json
import re

import pytest

from reconforge.infrastructure.postgres_customer_partial_return_rounding_schema import UPGRADE_SQL as ROUNDING_SQL
from reconforge.infrastructure.postgres_customer_partial_return_transfer_hooks import UPGRADE_SQL as CORRECTION_SQL
from reconforge.infrastructure.postgres_customer_partial_return_zero_stock_hooks import (
    _stock_close as retained_zero_stock_close,
)
from reconforge.infrastructure.postgres_customer_partial_returns_schema import UPGRADE_SQL as PARTIAL_OWNER_SQL
from reconforge.infrastructure.postgres_inventory_quantity_source_ownership import UPGRADE_SQL as QUANTITY_SQL
from reconforge.infrastructure.postgres_inventory_transfer_schema import OWNER_SQL as TRANSFER_OWNER_SQL
from reconforge.infrastructure.postgres_monetary_customer_returns_schema import DOWNGRADE_SQL as NATIVE_DOWNGRADE_SQL
from reconforge.infrastructure.postgres_monetary_customer_returns_schema import NATIVE_FUNCTION_SQL
from reconforge.infrastructure.postgres_monetary_inventory_shared_hooks import (
    _ZERO_FIFO_QUANTITY,
    DOWNGRADE_SQL,
    ORIGINAL_FUNCTIONS,
    UPGRADED_FUNCTIONS,
    preflight,
)
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import UPGRADED_FUNCTIONS as STOCK_FUNCTIONS
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import _body
from tests.monetary_capture_encoding import MAX_CAPTURE_BYTES, MAX_PACKET_BYTES, encode_monetary_capture


def test_raw_capture_encoding_preserves_canonical_utf8_and_final_newline() -> None:
    value = {"tables": {"opaque": ['{"text":"عربي","amount":1.00}']}, "checkpoint": "Original"}
    assert encode_monetary_capture(value) == (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def test_raw_capture_above_financial_snapshot_budget_is_valid() -> None:
    from reconforge.domain.finance_posting import MAX_SNAPSHOT_BYTES

    value = {"tables": {"opaque": ["x" * (MAX_SNAPSHOT_BYTES + 1)]}}
    encoded = encode_monetary_capture(value)
    assert MAX_SNAPSHOT_BYTES == 2_097_152 and MAX_SNAPSHOT_BYTES < len(encoded) < MAX_CAPTURE_BYTES
    assert json.loads(encoded) == value


@pytest.mark.parametrize(("packet", "maximum"), [(False, 4 * 1024 * 1024), (True, 64 * 1024 * 1024)])
def test_raw_capture_byte_limits_include_the_final_newline(packet: bool, maximum: int) -> None:
    assert (MAX_PACKET_BYTES if packet else MAX_CAPTURE_BYTES) == maximum
    # A JSON string has two quotes, plus the mandatory final newline.
    assert len(encode_monetary_capture("x" * (maximum - 3), packet=packet)) == maximum
    with pytest.raises(ValueError, match="declared raw JSON budget"):
        encode_monetary_capture("x" * (maximum - 2), packet=packet)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_raw_capture_rejects_nonfinite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        encode_monetary_capture({"nested": [value]})


def invalid_local_qualifiers(sql: str) -> list[str]:
    definitions = re.finditer(
        r"CREATE FUNCTION reconforge\.([a-z_]+)\([^)]*\).*?AS (\$[a-zA-Z_0-9]*\$)(.*?)\2;",
        sql, re.DOTALL,
    )
    invalid = []
    for definition in definitions:
        name, _, body = definition.groups()
        if "DECLARE" not in body:
            continue
        declarations = body[body.index("DECLARE") + len("DECLARE"):body.index("BEGIN")]
        local_names = re.findall(
            r"(?:^|;)\s*([a-z_]+)\s+(?:RECORD|TEXT|JSONB|INTEGER|BIGINT|NUMERIC|BOOLEAN)\b",
            declarations, re.IGNORECASE,
        )
        for local in local_names:
            if re.search(r"\b" + name + r"\." + local + r"\b", body) and not re.search(
                r"<<\s*" + name + r"\s*>>\s*DECLARE\b", body,
            ):
                invalid.append(name + "." + local)
    return sorted(invalid)


def test_every_emitted_function_qualified_local_binds_an_explicit_declare_block() -> None:
    assert invalid_local_qualifiers(NATIVE_FUNCTION_SQL) == []


@pytest.mark.parametrize("name,expected", [
    ("monetary_stock_source_close", ["monetary_stock_source_close.version"]),
    ("monetary_return_native_close", [
        "monetary_return_native_close.entry_id", "monetary_return_native_close.invoice_id",
        "monetary_return_native_close.movement_id",
    ]),
])
def test_missing_explicit_block_is_refused_even_when_implicit_function_label_exists(
    name: str, expected: list[str],
) -> None:
    assert invalid_local_qualifiers(NATIVE_FUNCTION_SQL.replace("<<" + name + ">>", "")) == expected


def _dispatch_aliases(name: str, upgraded: str) -> tuple[set[str], set[str]]:
    """Inspect only the new prefix; the complete historical tail stays exact."""
    _, original_body = _body(ORIGINAL_FUNCTIONS[name])
    _, upgraded_body = _body(upgraded)
    declarations, retained = original_body.split("BEGIN\n", 1)
    upgraded_declarations, extended = upgraded_body.split("BEGIN\n", 1)
    assert upgraded_declarations == declarations and extended.endswith(retained)
    prefix = extended[:-len(retained)]
    locals_ = set(re.findall(r"\b([a-z_][a-z_0-9]*)\s+(?:RECORD|TEXT|JSONB|INTEGER|BIGINT|NUMERIC|BOOLEAN)\b", declarations, re.I))
    aliases = set(re.findall(r"\b(?:FROM|JOIN)\s+reconforge\.[a-z_0-9]+\s+(?:AS\s+)?([a-z_][a-z_0-9]*)\b", prefix, re.I))
    return aliases, aliases & locals_


@pytest.mark.parametrize("name", [
    "customer_partial_return_zero_layer_guard", "customer_partial_return_zero_stock_active", "customer_partial_return_zero_stock_plan",
    "it1_cost_snapshot", "it1_cost_originals", "it1_stock_origins",
])
def test_physical_dispatch_aliases_cannot_shadow_retained_plpgsql_variables(name: str) -> None:
    aliases, conflicts = _dispatch_aliases(name, UPGRADED_FUNCTIONS[name])
    assert conflicts == set()
    assert all(alias.startswith("dispatch_") for alias in aliases)


@pytest.mark.parametrize("retained_record", ["document", "layer"])
def test_retained_record_alias_collision_is_detected_before_native_execution(retained_record: str) -> None:
    poisoned = UPGRADED_FUNCTIONS["it1_cost_snapshot"].replace("dispatch_document", retained_record)
    assert _dispatch_aliases("it1_cost_snapshot", poisoned)[1] == {retained_record}


def test_zero_fifo_extension_preserves_the_complete_original_units_positive_sum_and_claim_law() -> None:
    original = ORIGINAL_FUNCTIONS["inventory_quantity_free_fifo"]
    assert hashlib.sha256(_body(original)[1].encode()).hexdigest() == "815bcf89c963b301a198b496504621bbac3b113fa4e60a653727897796e8691f"
    upgraded = UPGRADED_FUNCTIONS["inventory_quantity_free_fifo"]
    declarations, extended = _body(upgraded)[1].split("BEGIN\n", 1)
    assert declarations.startswith("\nDECLARE remaining NUMERIC;claimed NUMERIC;native RECORD;")
    restored = declarations[:declarations.index("zero_candidate RECORD;")] + "\nBEGIN\n" + extended.replace(_ZERO_FIFO_QUANTITY, "", 1)
    assert restored == _body(original)[1]
    assert "remaining_quantity_scaled')::numeric<=restitution_quantity" not in upgraded


def test_zero_fifo_source_proof_is_conditional_and_precedes_the_unchanged_global_claim_deduction() -> None:
    body = _body(UPGRADED_FUNCTIONS["inventory_quantity_free_fifo"])[1]
    loop = body.index(" FOR zero_candidate IN")
    relevance = body.index("dispatch_layer.remaining_quantity_scaled>dispatch_layer.original_quantity_scaled-(SELECT COALESCE(sum(dispatch_consumption.quantity_scaled),0)")
    first_private = body.index("FROM reconforge.customer_partial_return_restorations")
    new_tables = body.index("FROM reconforge.customer_partial_return_monetary_restorations")
    ordinary_exclusion = body.index("IF restitution_quantity<=0 THEN CONTINUE;END IF;")
    snapshot = body.index("quantity_cost:=reconforge.monetary_quantity_cost_snapshot(")
    originals = body.index("PERFORM reconforge.it1_cost_originals(t,quantity_cost)")
    current_layer = body.index("quantity_members=1 AND quantity_source->'layer'=zero_candidate.layer_json")
    signed = body.index("PERFORM reconforge.it1_assert(restitution_quantity>0,")
    add = body.index("remaining:=remaining+(zero_candidate.layer_json->>'remaining_quantity_scaled')::numeric;")
    claimed = body.index(" SELECT COALESCE(sum(g.quantity_scaled),0) INTO claimed")
    assert loop < relevance < first_private < new_tables < ordinary_exclusion < snapshot < originals < current_layer < signed < add < claimed
    assert "WHERE dispatch_consumption.tenant_id=dispatch_layer.tenant_id AND dispatch_consumption.cost_layer_id=dispatch_layer.id)" in body[relevance:first_private]
    assert "dispatch_layer.remaining_quantity_scaled>0 AND dispatch_layer.remaining_value_minor=0" in body[loop:new_tables]
    assert body.count("quantity_cost:=reconforge.monetary_quantity_cost_snapshot(") == 1
    assert body.count("remaining:=remaining+") == 1
    assert body.count("RETURN remaining-claimed;") == 1
    # The original positive-only prefix performs no private restitution reads.
    assert "customer_partial_return_" not in body[:loop]
    assert "set_config" not in body and "EXCEPTION WHEN" not in body and "has_table_privilege" not in body


def test_quantity_and_legacy_fact_proof_profiles_restore_exact_original_bodies() -> None:
    assert len(ORIGINAL_FUNCTIONS) == len(UPGRADED_FUNCTIONS) == 11
    original = ORIGINAL_FUNCTIONS["inventory_quantity_free_fifo"]
    upgraded = UPGRADED_FUNCTIONS["inventory_quantity_free_fifo"]
    header = original.split("AS $quantity$", 1)[0]
    assert upgraded.split("AS $quantity$", 1)[0] == header.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    assert "LANGUAGE plpgsql STABLE SET search_path=pg_catalog" in header
    assert original.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) in DOWNGRADE_SQL
    for definition, is_upgraded in ((original, False), (upgraded, True)):
        assertion = preflight(upgraded=is_upgraded)
        assert assertion.count("Retained physical execution contract drift") == 11
        assert "inventory_quantity_free_fifo(text,text,text,text)" in assertion
        assert hashlib.sha256(_body(definition)[1].encode()).hexdigest() in assertion


def _function_bodies(*sources: str) -> dict[str, str]:
    """Read generated bodies in installation order; later replacements win."""
    functions = {}
    for source in sources:
        for definition in re.split(r"(?=CREATE(?: OR REPLACE)? FUNCTION reconforge\.)", source):
            name = re.match(r"CREATE(?: OR REPLACE)? FUNCTION reconforge\.([a-z_0-9]+)\(", definition)
            if name is None:
                continue
            delimiter = re.search(r"\bAS\s+(\$[a-z_0-9]*\$)", definition, re.I)
            assert delimiter is not None
            functions[name[1]] = definition[delimiter.end():definition.index(delimiter[1], delimiter.end())]
    return functions


def _without_unscoped_ar_gates(functions: dict[str, str]) -> dict[str, str]:
    """Restore the exact full-scope bodies for the older golden contracts."""
    restored = dict(functions)
    restored["monetary_stock_invoice_balance"] = restored["monetary_stock_invoice_balance"].replace(
        " IF invoice_owner.organization_id IS NULL OR invoice_owner.legal_entity_id IS NULL THEN RETURN NULL;END IF;\n", "", 1)
    namespace = restored["monetary_namespace"]
    for image in ("OLD", "NEW"):
        gate = (
            "   IF invoice_owner.id IS NOT NULL AND(invoice_owner.organization_id IS NULL OR invoice_owner.legal_entity_id IS NULL) THEN\n"
            f"    IF TG_TABLE_NAME='ar_invoice_lines' THEN RETURN {image};END IF;\n"
            "    SELECT id,organization_id,legal_entity_id INTO receipt_owner FROM reconforge.ar_receipts "
            f"WHERE tenant_id={image}.tenant_id AND id=to_jsonb({image})->>'receipt_id';\n"
            "    IF receipt_owner.id IS NOT NULL AND(receipt_owner.organization_id IS NULL OR receipt_owner.legal_entity_id IS NULL) "
            f"THEN RETURN {image};END IF;\n   END IF;\n"
        )
        namespace = namespace.replace(gate, "", 1)
    restored["monetary_namespace"] = namespace.replace(";receipt_owner RECORD;", ";", 1)
    callback = restored["monetary_return_native_close"]
    start = callback.index("  -- A fixed monetary owner requires full native AR scope.")
    end = callback.index("  IF TG_TABLE_NAME='stock_sales_monetary_origins' THEN", start)
    restored["monetary_return_native_close"] = (callback[:start] + callback[end:]).replace(
        ";invoice_scope RECORD;receipt_scope RECORD;", ";", 1)
    return restored


def test_cached_serializer_preserves_every_existing_native_check_and_retained_function() -> None:
    functions = _function_bodies(NATIVE_FUNCTION_SQL)
    previous = {name: body.replace("reconforge.monetary_digest(", "reconforge.irp_digest(")
                for name, body in functions.items() if name not in {"monetary_canonical", "monetary_digest"}}
    previous = _without_unscoped_ar_gates(previous)
    callback = previous["monetary_return_native_close"]
    start = callback.index("  -- These financial envelopes cannot mutate quantity inputs.")
    end = callback.index(" END LOOP;", start)
    previous["monetary_return_native_close"] = callback[:start] + (
        "  PERFORM reconforge.monetary_stock_close(candidate.tenant_id,candidate.stock_order_id);\n") + callback[end:]
    # Exact ab4bbaf7 predecessor inventory: only the digest call target changes.
    assert len(previous) == 56 and len(functions) == 58
    assert hashlib.sha256(json.dumps(previous, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == (
        "299256b3a36e2d4eb34d84fcd97673a5dbc7a65fc690d0c10a3d7af2bd338de6")
    assert sum(body.count("reconforge.monetary_digest(") for body in previous.values()) == 0
    assert NATIVE_FUNCTION_SQL.count("CREATE FUNCTION reconforge.irp_") == 0
    assert "reconforge.irp_digest(" not in NATIVE_FUNCTION_SQL
    canonical = functions["monetary_canonical"]
    assert "IF value IS NULL THEN RETURN NULL;END IF;" in canonical
    assert "ORDER BY k COLLATE \"C\"" in canonical and "to_jsonb(k)::text" in canonical
    assert "WITH ORDINALITY e(v,n)" in canonical and "ORDER BY n" in canonical
    assert "ELSE result:=value::text;" in canonical
    assert functions["monetary_digest"].strip() == (
        "SELECT encode(sha256(convert_to(reconforge.monetary_canonical(value),'UTF8')),'hex')")
    for name in ("monetary_digest", "monetary_canonical"):
        assert f"DROP FUNCTION reconforge.{name}(JSONB);" in NATIVE_DOWNGRADE_SQL


def test_only_fixed_financial_callbacks_use_full_source_proof_with_default_live_capacity() -> None:
    body = _function_bodies(NATIVE_FUNCTION_SQL)["monetary_return_native_close"]
    start = body.index("  -- These financial envelopes cannot mutate quantity inputs.")
    end = body.index(" END LOOP;", start)
    branch = body[start:end]
    tables = set(re.findall(r"'([a-z_]+)'", branch))
    assert tables == {
        "operational_fx_sources", "operational_fx_plans", "operational_fx_reviews", "operational_fx_links", "operational_fx_commands",
        "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions", "finance_posting_effects",
        "ar_invoices", "ar_invoice_lines", "ar_receipts", "ar_receipt_allocations", "domain_audit_events", "outbox_events",
    }
    assert branch.count("IF TG_TABLE_NAME IN(") == 1 and branch.count("ELSE") == 1
    source, live = branch.split("  ELSE\n")
    assert source.count("PERFORM reconforge.monetary_stock_source_close(candidate.tenant_id,candidate.stock_order_id);") == 1
    assert "monetary_stock_close(" not in source
    assert live == "   PERFORM reconforge.monetary_stock_close(candidate.tenant_id,candidate.stock_order_id);\n  END IF;\n"
    assert "RETURN" not in branch
    assert body.index("FOR changed IN SELECT previous") < body.index("FOR candidate IN SELECT DISTINCT") < start


def test_event_callbacks_classify_each_image_before_any_private_owner_lookup() -> None:
    body = _function_bodies(NATIVE_FUNCTION_SQL)["monetary_return_native_close"]
    start = body.index("  ELSIF TG_TABLE_NAME IN('domain_audit_events','outbox_events') THEN")
    event = body[start:body.index("  IF plan_id IS NOT NULL THEN", start)]
    stock, correction = event.split("   ELSIF COALESCE(reference,'')~'^(CR3|CRF3|CR3R|CRF3R)-[0-9a-f]{32}$' THEN")
    correction, fx = correction.split("   ELSIF COALESCE(reference,'')~'^FX1-[0-9a-f]{32}$' THEN")
    assert "THEN changed->>'object_id' ELSE changed->>'aggregate_id' END" in stock
    assert "THEN changed->>'object_type' ELSE changed->>'aggregate_type' END)='stock_sales'" in stock
    assert set(re.findall(r"(?:FROM|JOIN) reconforge\.([a-z_]+)", stock)) == {"stock_sales_orders"}
    assert "fixed.source->>'schema_version'='stock-sales-monetary-order-v2'" in stock
    assert "IF stock_id IS NULL THEN CONTINUE;END IF;" in stock
    assert "operational_fx_" not in correction
    assert "event_owner.audit_event_id=changed->>'id' OR event_owner.outbox_event_id=changed->>'event_id'" in correction
    fx_source = fx.index("native_source.payload->>'schema_version'='operational-fx-stock-source-v2'")
    assert "native_plan.id=reference" in fx[:fx_source]
    assert fx_source < fx.index("THEN CONTINUE;END IF;") < fx.index("FROM reconforge.stock_sales_monetary_origins")
    assert "changed->>'id' IN(fx_plan.audit_event_id,fx_review.audit_event_id,fx_link.audit_event_id)" in fx
    assert "changed->>'event_id' IN(fx_plan.outbox_event_id,fx_review.outbox_event_id,fx_link.outbox_event_id)" in fx
    assert "   ELSE CONTINUE;\n   END IF;" in fx
    assert "RETURN" not in event and "UNION" not in event
    assert body.index("FOR changed IN SELECT previous WHERE previous IS NOT NULL UNION SELECT current_row WHERE current_row IS NOT NULL LOOP") < start
    assert body.index("PERFORM reconforge.monetary_stock_close(candidate.tenant_id,candidate.stock_order_id);") > start


def test_legacy_operational_ids_cannot_enter_the_new_event_owner_queries() -> None:
    body = _function_bodies(NATIVE_FUNCTION_SQL)["monetary_return_native_close"]
    event = body[body.index("  ELSIF TG_TABLE_NAME IN('domain_audit_events','outbox_events') THEN"):body.index("  IF plan_id IS NOT NULL THEN")]
    expressions = re.findall(r"ELSIF COALESCE\(reference,''\)~'([^']+)' THEN", event)
    assert len(expressions) == 2
    for prefix in ("OPS1", "CR1", "CRF1", "CR1R", "CRF1R", "CR2", "CRF2", "CR2R", "CRF2R"):
        assert not any(re.fullmatch(pattern, prefix + "-" + "a" * 32) for pattern in expressions)
    for prefix in ("CR3", "CRF3", "CR3R", "CRF3R", "FX1"):
        assert sum(re.fullmatch(pattern, prefix + "-" + "a" * 32) is not None for pattern in expressions) == 1


def test_event_dispatch_change_preserves_finance_admission_and_delivery_envelope_guards() -> None:
    body = _function_bodies(NATIVE_FUNCTION_SQL)["monetary_return_native_close"]
    finance = body[body.index("  IF entry_id IS NOT NULL THEN"):body.index("  IF movement_id IS NOT NULL THEN")]
    delivery = body[body.index(" IF TG_TABLE_NAME='outbox_events' AND TG_OP='UPDATE'"):body.index(" FOR changed IN")]
    # B554 finance admission and the prior nine-field delivery guard are fixed
    # byte contracts; neither surface belongs to this event-only repair.
    assert hashlib.sha256(finance.encode()).hexdigest() == "095bb662dbbbeda979e8ecd2699c7d41f2c6fc6025b8622442308f473d55c0f4"
    assert hashlib.sha256(delivery.encode()).hexdigest() == "59f12ca824c593c5d4fba312be2a6fb93fbc952a94d08024fc9c5ee52e004a8b"


def test_unscoped_ar_balance_requires_a_visible_header_before_excluding_private_ownership() -> None:
    body = _function_bodies(NATIVE_FUNCTION_SQL)["monetary_stock_invoice_balance"]
    gate = " IF invoice_owner.organization_id IS NULL OR invoice_owner.legal_entity_id IS NULL THEN RETURN NULL;END IF;\n"
    assert body.count(gate) == 1
    assert body.index("invoice_owner.id IS NOT NULL") < body.index(gate) < body.index("FROM reconforge.stock_sales_monetary_origins")
    assert hashlib.sha256(body.replace(gate, "", 1).encode()).hexdigest() == "bb3b6e13d89f0712c2a6a2c5c980d381e2f4b4162eba3fb9e316503f687e5de8"


def test_unscoped_namespace_children_require_actual_headers_and_preserve_every_owned_check() -> None:
    body = _function_bodies(NATIVE_FUNCTION_SQL)["monetary_namespace"]
    for image in ("OLD", "NEW"):
        gate = (
            "   IF invoice_owner.id IS NOT NULL AND(invoice_owner.organization_id IS NULL OR invoice_owner.legal_entity_id IS NULL) THEN\n"
            f"    IF TG_TABLE_NAME='ar_invoice_lines' THEN RETURN {image};END IF;\n"
            "    SELECT id,organization_id,legal_entity_id INTO receipt_owner FROM reconforge.ar_receipts "
            f"WHERE tenant_id={image}.tenant_id AND id=to_jsonb({image})->>'receipt_id';\n"
            "    IF receipt_owner.id IS NOT NULL AND(receipt_owner.organization_id IS NULL OR receipt_owner.legal_entity_id IS NULL) "
            f"THEN RETURN {image};END IF;\n   END IF;\n"
        )
        assert body.count(gate) == 1
        body = body.replace(gate, "", 1)
    body = body.replace(";receipt_owner RECORD;", ";", 1)
    assert hashlib.sha256(body.encode()).hexdigest() == "b9d186665c578e1a296a7303952ba3086e8fc5e019d85ef15c1239256da97b45"


def test_unscoped_native_images_cannot_hide_a_missing_or_fully_scoped_allocation_parent() -> None:
    body = _function_bodies(NATIVE_FUNCTION_SQL)["monetary_return_native_close"]
    start = body.index("  -- A fixed monetary owner requires full native AR scope.")
    end = body.index("  IF TG_TABLE_NAME='stock_sales_monetary_origins' THEN", start)
    gate = body[start:end]
    assert body.index("FOR changed IN SELECT previous") < start
    assert "RETURN" not in gate
    assert "changed->>'id' IS NOT NULL AND(changed->>'organization_id' IS NULL OR changed->>'legal_entity_id' IS NULL)" in gate
    invoice = gate.index("IF invoice_scope.id IS NOT NULL AND(invoice_scope.organization_id IS NULL OR invoice_scope.legal_entity_id IS NULL) THEN")
    receipt = gate.index("IF receipt_scope.id IS NOT NULL AND(receipt_scope.organization_id IS NULL OR receipt_scope.legal_entity_id IS NULL) THEN CONTINUE;END IF;")
    assert invoice < gate.index("IF TG_TABLE_NAME='ar_invoice_lines' THEN CONTINUE;END IF;") < gate.index("FROM reconforge.ar_receipts") < receipt
    assert set(re.findall(r"FROM reconforge\.([a-z_]+)", gate)) == {"ar_invoices", "ar_receipts"}
    restored = (body[:start] + body[end:]).replace(";invoice_scope RECORD;receipt_scope RECORD;", ";", 1)
    assert hashlib.sha256(restored.encode()).hexdigest() == "bba8e1b00f9014c87e7063a103f8cf87e85484c0d753795cfda9d0bafd44a4da"


def _proof_call_graph(functions: dict[str, str]) -> dict[str, set[str]]:
    graph = {name: set(re.findall(r"reconforge\.([a-z_0-9]+)\(", body)) for name, body in functions.items()}
    # The original adoption loop sees only Posted movements. Its direct close
    # call is explicitly phase2; phase1 uses native_admit, never generic close.
    # Model that actual finite state, without deleting the live phase1 guard.
    for name in ("it1_stock_origins", "monetary_transfer_stock_origins"):
        assert "IF source.phase=2 THEN PERFORM reconforge.it1_close(t,source.id);" in functions[name]
        assert "PERFORM reconforge.it1_native_admit(t,physical.head,source.native_creation_json->'head','inventory_movements:UPDATE');" in functions[name]
        graph[name].remove("it1_close")
        graph[name].add("it1_close@posted")
    live_capacity = "   PERFORM reconforge.inventory_quantity_check_capacity(t,s.workspace_id,s.legal_entity_id,s.item_id,s.from_location_id);"
    assert functions["it1_close"].count(live_capacity) == 1
    assert "IF phase=1 THEN PERFORM reconforge.it1_assert(c.state='Active'" in functions["it1_close"]
    posted_close = functions["it1_close"].replace(live_capacity, "", 1)
    graph["it1_close@posted"] = set(re.findall(r"reconforge\.([a-z_0-9]+)\(", posted_close))
    return graph


def _reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    pending = list(graph.get(start, set()))
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(graph.get(name, set()) - seen)
    return seen


def test_source_physical_proof_and_full_source_body_are_exact_except_capacity_extraction_and_label() -> None:
    functions = _function_bodies(NATIVE_FUNCTION_SQL)
    assert len(functions) == 58
    old_full = functions["monetary_stock_source_close"].replace("monetary_stock_source_close", "monetary_stock_close").replace(
        "reconforge.monetary_digest(", "reconforge.irp_digest(")
    assert hashlib.sha256(old_full.encode()).hexdigest() == "3b6fc98713b56b8380f85835bb8ecba5f3c30df8fd90396bc90b93921e6f811e"
    physical = functions["monetary_stock_physical_close"].replace("reconforge.monetary_digest(", "reconforge.irp_digest(")
    anchor = "MESSAGE='Reservation phase differs from source owner.';\n END IF;\n"
    capacity = " IF r.order_id IS NOT NULL THEN PERFORM reconforge.stock_sales_capacity(t,d.workspace_id,d.legal_entity_id,d.location_id,d.item_id); END IF;\n"
    assert physical.count(anchor) == 1 and "stock_sales_capacity" not in physical
    assert hashlib.sha256(physical.replace(anchor, anchor + capacity, 1).encode()).hexdigest() == "c2cb58bf322f73f4e0fa728add6580de7baff2ee757b076d03922823b8e9e056"
    wrapper = functions["monetary_stock_close"]
    assert wrapper.index("PERFORM reconforge.monetary_stock_source_close(t,target);") < wrapper.index("IF reservation_owner.order_id IS NOT NULL THEN") < wrapper.index("PERFORM reconforge.stock_sales_capacity(")
    assert "RETURN;" not in wrapper and "origin_owner" not in wrapper and "reservation_owner.state" not in wrapper
    assert NATIVE_DOWNGRADE_SQL.index("DROP FUNCTION reconforge.monetary_stock_close(TEXT,TEXT);") < NATIVE_DOWNGRADE_SQL.index("DROP FUNCTION reconforge.monetary_stock_source_close(TEXT,TEXT);")
    retained_proof = _function_bodies(retained_zero_stock_close())["customer_partial_return_zero_stock_close"]
    retained_capacity = " IF r IS NOT NULL THEN PERFORM reconforge.stock_sales_capacity(t,d.workspace_id,d.legal_entity_id,d.location_id,d.item_id); END IF;\n"
    assert functions["monetary_retained_zero_stock_source_close"].replace(
        "reconforge.monetary_digest(", "reconforge.irp_digest(") == retained_proof.replace(retained_capacity, "", 1)
    old_consumption = ORIGINAL_FUNCTIONS["customer_partial_return_zero_consumption"]
    proof_consumption = UPGRADED_FUNCTIONS["customer_partial_return_zero_consumption"]
    assert proof_consumption.replace("CREATE OR REPLACE FUNCTION", "CREATE FUNCTION", 1).replace(
        "monetary_retained_zero_stock_source_close", "customer_partial_return_zero_stock_close") == old_consumption
    assert old_consumption.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) in DOWNGRADE_SQL


def test_complete_cost_proof_graph_exposes_both_old_cycles_and_retains_live_owner_capacity() -> None:
    functions = _function_bodies(QUANTITY_SQL, TRANSFER_OWNER_SQL, PARTIAL_OWNER_SQL, CORRECTION_SQL, ROUNDING_SQL,
        NATIVE_FUNCTION_SQL, "\n".join(STOCK_FUNCTIONS.values()), "\n".join(UPGRADED_FUNCTIONS.values()))
    graph = _proof_call_graph(functions)
    quantity_reachable = _reachable(graph, "inventory_quantity_free_fifo")
    reachable = quantity_reachable | _reachable(graph, "it1_cost_snapshot")
    assert {"monetary_transfer_stock_origins", "monetary_stock_source_close", "monetary_stock_physical_close",
            "monetary_zero_consumption", "monetary_stock_zero_facts", "monetary_stock_zero_plan", "it1_cost_originals",
            "customer_partial_return_transfer_correction_dispatch", "monetary_transfer_correction", "monetary_partial_close",
            "monetary_stock_prefix", "monetary_fx_close", "it1_native_admit",
            "monetary_retained_zero_stock_source_close", "customer_partial_return_zero_consumption"} <= reachable
    assert not {"stock_sales_capacity", "inventory_quantity_check_capacity", "inventory_quantity_free_fifo", "monetary_stock_close"} & reachable
    assert not {"it1_stock_origins", "monetary_transfer_stock_origins", "it1_native_admit"} & quantity_reachable
    # These retained external leaves were independently reviewed as pure or
    # SELECT-only (including the finite SELECT-only IRP artifact dispatcher).
    # Keep the boundary closed: a newly unresolved helper requires review.
    assert reachable - set(graph) == {
        "collection_invoice_close", "customer_partial_return_invoice_credited", "customer_partial_return_native_source",
        "customer_return_authority", "customer_return_credited", "customer_return_inverse_entry", "fr_snapshot", "fx_assert",
        "fx_convert", "fx_event", "fx_minor", "fx_object", "fx_policy", "fx_rate", "irp_assert_complete", "irp_canonical",
        "irp_digest", "irp_scope", "irp_text", "irp_timestamp", "sales_revenue_actor", "sales_revenue_policy_matches", "stock_sales_stage",
    }
    assert "stock_sales_capacity" in _reachable(graph, "monetary_stock_close")
    assert "monetary_stock_close" in graph["monetary_return_native_close"]
    assert "monetary_stock_close" in graph["stock_sales_close"]
    # Reconstruct the witnessed pre-fix calls: both must expose the real cycle.
    old = dict(functions)
    old["inventory_quantity_free_fifo"] = old["inventory_quantity_free_fifo"].replace("monetary_quantity_cost_snapshot", "it1_cost_snapshot")
    old["monetary_stock_close"] = old["monetary_stock_source_close"]
    old["monetary_stock_physical_close"] += " PERFORM reconforge.stock_sales_capacity(t,d.workspace_id,d.legal_entity_id,d.location_id,d.item_id);"
    old["monetary_transfer_stock_origins"] = old["monetary_transfer_stock_origins"].replace("monetary_stock_source_close", "monetary_stock_close")
    old["customer_partial_return_zero_consumption"] = _function_bodies(ORIGINAL_FUNCTIONS["customer_partial_return_zero_consumption"])["customer_partial_return_zero_consumption"]
    old_graph = _proof_call_graph(old)
    for entry in ("monetary_transfer_stock_origins", "monetary_zero_consumption"):
        assert {"stock_sales_capacity", "inventory_quantity_check_capacity", "inventory_quantity_free_fifo"} <= _reachable(old_graph, entry)
    assert {"stock_sales_capacity", "inventory_quantity_check_capacity", "inventory_quantity_free_fifo"} <= _reachable(old_graph, "customer_partial_return_zero_consumption")


def test_quantity_snapshot_omits_only_adoption_and_has_no_other_admission_callsite() -> None:
    functions = _function_bodies(ROUNDING_SQL, NATIVE_FUNCTION_SQL, "\n".join(UPGRADED_FUNCTIONS.values()))
    full = functions["monetary_transfer_cost_snapshot"]
    quantity = functions["monetary_quantity_cost_snapshot"]
    adoption = " PERFORM reconforge.monetary_transfer_stock_origins(t,w,o,e,i);\n"
    assert full.count(adoption) == 1 and quantity == full.replace(adoption, "", 1)
    callers = {name for name, body in functions.items() if "reconforge.monetary_quantity_cost_snapshot(" in body}
    assert callers == {"inventory_quantity_free_fifo"}
    assert "PERFORM reconforge.it1_cost_originals(t,quantity_cost);" in functions["inventory_quantity_free_fifo"]
    for name in ("monetary_stock_zero_cost", "customer_partial_return_zero_stock_cost"):
        assert "cost:=reconforge.it1_cost_snapshot(t,w,o,e,i);" in functions[name]
    assert "DROP FUNCTION reconforge.monetary_quantity_cost_snapshot(TEXT,TEXT,TEXT,TEXT,TEXT);" in NATIVE_DOWNGRADE_SQL
