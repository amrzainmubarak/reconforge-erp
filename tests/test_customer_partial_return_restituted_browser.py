"""Synthetic custody controls only; these tests do not execute a native sale."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tests import customer_partial_return_restituted_browser as observer
from tests.customer_partial_return_remainder_browser import TABLES

OLD = "CR2-" + "a" * 32
NEW = "CR2-" + "b" * 32
DIGEST = "c" * 64


def test_runner_restore_exports_exact_independent_seventy_nine_table_scope() -> None:
    from tests.customer_partial_return_restituted_cycle_oracle import TABLES as INDEPENDENT_TABLES
    assert observer.TABLES == INDEPENDENT_TABLES and len(set(observer.TABLES)) == 79


def runtime(dsn: str = "original") -> Any:
    return SimpleNamespace(tenant="synthetic", factory=SimpleNamespace(settings=SimpleNamespace(dsn=dsn)))


def tables(stage: int, audit: int = 0) -> dict[str, list[str]]:
    value: dict[str, list[str]] = {name: [] for name in TABLES}
    value["finance_entry_lines"] = [f'{{"id":"business-{stage}"}}']
    value["domain_audit_events"] = [f'{{"id":"audit-{n:03}"}}' for n in range(audit)]
    value["domain_audit_ledger_state"] = [f'{{"version":{audit}}}']
    return value


def state(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    values = {"stage": 0, "audit": 0}
    def snapshot(_: Any, source: str, case: str) -> tuple[int, dict[str, list[str]], dict[str, Any] | None]:
        assert case == "zero" and source in {"original", "resale"}
        version = int(values["stage"] >= (1 if source == "original" else 3))
        last = {"sequence": 1, "plan_id": OLD if source == "original" else NEW, "plan_digest": DIGEST, "phase": 2} if version else None
        return version, tables(values["stage"], values["audit"]), last
    monkeypatch.setattr(observer, "_snapshot", snapshot)
    def audit(before: Any, after: Any, tenant: str) -> None:
        assert tenant == "synthetic"
        excluded = {"domain_audit_events", "domain_audit_ledger_state"}
        if {k: v for k, v in before.items() if k not in excluded} != {k: v for k, v in after.items() if k not in excluded}:
            raise ValueError("Synthetic audit-only control refused.")
    monkeypatch.setattr(observer, "_audit", audit)
    return values


def capture(root: Path, number: int, *, observation: str | None = None, refusal: dict[str, Any] | None = None) -> None:
    plan = OLD if number == 1 or observation == "DependencyRefusal" else NEW if number == 3 else None
    observer.capture_restituted_browser(runtime(), "original", root, checkpoint=observer.CHECKPOINTS[number],
        resale="resale" if number >= 2 else None, posted_plan_id=plan, plan_digest=DIGEST if plan else None,
        observation=observation, refusal=refusal)


def refusal() -> dict[str, Any]:
    return {"method": "POST", "route": f"/api/v2/customer-partial-returns/plans/{OLD}/reversals", "status": 409,
            "code": "customer_partial_return_reversal_dependency"}


def complete(root: Path, current: dict[str, int]) -> None:
    for number in range(4):
        current["stage"] = number
        capture(root, number)
    current["audit"] = 2
    capture(root, 3, observation="RetainedReplay")
    current["audit"] = 3
    capture(root, 3, observation="DependencyRefusal", refusal=refusal())


def test_four_immutable_checkpoints_three_observations_and_exact_populated_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / observer.FAMILY
    current = state(monkeypatch)
    complete(root, current)
    originals = [(root / f"checkpoint-{n}.json").read_bytes() for n in range(4)]
    packet = observer.assemble_restituted_browser(root, tenant="synthetic", original="original", resale="resale")
    assert set(packet) == {"schema_version", "tenant_id", "original_source_order_id", "resale_source_order_id", "captures"}
    assert [value["checkpoint"] for value in packet["captures"]] == list(observer.CHECKPOINTS)
    assert all(set(value) == {"checkpoint", "tables"} and set(value["tables"]) == set(TABLES) for value in packet["captures"])
    assert all(b'resale_source_order_id' not in value for value in originals)
    current["audit"] = 4
    proof = observer.verify_restituted_browser(runtime(), custody_root=root, original="original", resale="resale", original_app_dsn="original")
    repeated = observer.verify_restituted_browser(runtime(), custody_root=root, original="original", resale="resale", original_app_dsn="original")
    restored = observer.verify_restituted_browser(runtime("restored"), custody_root=root, original="original", resale="resale", original_app_dsn="original")
    assert proof == repeated == restored and proof["checkpoints"] == 4 and len(proof["tables"]) == 79
    assert observer.verify_seeded_restituted_browser(runtime(), custody_root=root, original="original", original_app_dsn="original") == proof
    assert originals == [(root / f"checkpoint-{n}.json").read_bytes() for n in range(4)]
    assert {path.name for path in (tmp_path / observer.OBSERVATIONS).iterdir()} == {observer.OBSERVATION_PACKET, *(name + ".json" for name in observer.KINDS)}
    restored_packet = observer.parse_json_document((root / observer.RESTORE).read_text(encoding="utf-8"), reject_fractional_numbers=True)
    assert restored_packet == {"schema_version": "customer-partial-return-restituted-restored-input-v1", "tenant_id": "synthetic",
        "original_source_order_id": "original", "resale_source_order_id": "resale", "tables": tables(3, 4)}


def test_failed_observation_retains_complete79_without_replacing_economic_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / observer.FAMILY
    current = state(monkeypatch)
    for number in range(4):
        current["stage"] = number
        capture(root, number)
    before = (root / "checkpoint-3.json").read_bytes()
    changed = tables(8)
    monkeypatch.setattr(observer, "_snapshot", lambda *args: (1, changed, {"sequence": 1, "plan_id": NEW, "plan_digest": DIGEST, "phase": 2}))
    with pytest.raises(ValueError):
        capture(root, 3, observation="RetainedReplay")
    failure_path, = (tmp_path / observer.REFUSED).iterdir()
    failure = cast(dict[str, Any], observer.parse_json_document(failure_path.read_text(encoding="utf-8"), reject_fractional_numbers=True))
    assert failure["candidate"]["tables"] == changed and len(changed) == 79
    assert (root / "checkpoint-3.json").read_bytes() == before


@pytest.mark.parametrize("variant", ["method", "route", "status", "bool-status", "code", "extra"])
def test_dependency_refusal_receipt_has_exact_finite_http_affinity(variant: str) -> None:
    value = deepcopy(refusal())
    if variant == "method":
        value["method"] = "GET"
    elif variant == "route":
        value["route"] = f"/api/v2/customer-partial-returns/plans/{NEW}/reversals"
    elif variant == "status":
        value["status"] = 200
    elif variant == "bool-status":
        value["status"] = True
    elif variant == "code":
        value["code"] = "other"
    else:
        value["secret"] = "private"
    with pytest.raises(ValueError):
        observer._refusal(value, kind="DependencyRefusal", original_plan=OLD)


@pytest.mark.parametrize("variant", ["gap", "unknown-file", "wrong-family", "relative", "symlink", "missing-resale", "same-source", "wrong-plan"])
def test_refuses_unowned_incoherent_or_unbound_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str) -> None:
    root = tmp_path / observer.FAMILY
    current = state(monkeypatch)
    capture(root, 0)
    if variant == "gap":
        (root / "checkpoint-2.json").write_bytes((root / "checkpoint-0.json").read_bytes())
    elif variant == "unknown-file":
        (root / "unexpected.json").write_text("{}", encoding="utf-8")
    elif variant == "wrong-family":
        root = tmp_path / "unowned"
    elif variant == "relative":
        root = Path(observer.FAMILY)
    elif variant == "symlink":
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == root or original(path))
    elif variant in {"missing-resale", "same-source"}:
        current["stage"] = 1
        capture(root, 1)
        current["stage"] = 2
        with pytest.raises(ValueError):
            observer.capture_restituted_browser(runtime(), "original", root, checkpoint="ResaleInvoiced", resale=None if variant == "missing-resale" else "original")
        return
    else:
        current["stage"] = 1
        with pytest.raises(ValueError):
            observer.capture_restituted_browser(runtime(), "original", root, checkpoint="ZeroReturn", posted_plan_id=NEW, plan_digest=DIGEST)
        return
    with pytest.raises(ValueError):
        capture(root, 0)


def test_restore_cannot_accept_changed_business_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / observer.FAMILY
    current = state(monkeypatch)
    complete(root, current)
    observer.verify_restituted_browser(runtime(), custody_root=root, original="original", resale="resale", original_app_dsn="original")
    monkeypatch.setattr(observer, "_snapshot", lambda *args: (1, tables(9, 3), {"sequence": 1, "plan_id": NEW, "plan_digest": DIGEST, "phase": 2}))
    with pytest.raises(ValueError):
        observer.verify_restituted_browser(runtime("restored"), custody_root=root, original="original", resale="resale", original_app_dsn="original")


def test_real_c_reader_accepts_complete_producer_wire_without_reusing_financial_math(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic row transport bridge; the C reader owns every expected amount."""
    from tests import customer_partial_return_restituted_cycle_oracle as independent
    from tests.test_customer_partial_return_restituted_cycle_oracle import observations_fixture
    expected, observations, _restored = observations_fixture()
    original, resale, tenant = (expected[key] for key in ("original_source_order_id", "resale_source_order_id", "tenant_id"))
    selected = {"tables": expected["captures"][0]["tables"]}
    def snapshot(_: Any, source: str, case: str) -> tuple[int, dict[str, list[str]], dict[str, Any] | None]:
        assert case == "zero"
        rows = independent.base._rows(selected["tables"])
        plans = [row for row in rows["customer_partial_return_plans"] if row["source_order_id"] == source]
        plan = plans[0] if plans else None
        return len(plans), selected["tables"], ({"phase": plan["phase"], "plan_id": plan["id"], "plan_digest": plan["plan_digest"]} if plan else None)
    monkeypatch.setattr(observer, "_snapshot", snapshot)
    role = runtime()
    role.tenant = tenant
    root = tmp_path / observer.FAMILY
    for index, value in enumerate(expected["captures"]):
        selected["tables"] = value["tables"]
        plans = independent.base._rows(value["tables"])["customer_partial_return_plans"]
        plan = next((row for row in plans if row["source_order_id"] == (original if index == 1 else resale)), None) if index in {1, 3} else None
        observer.capture_restituted_browser(role, original, root, checkpoint=value["checkpoint"], resale=resale if index >= 2 else None,
            posted_plan_id=plan["id"] if plan else None, plan_digest=plan["plan_digest"] if plan else None)
    for value in observations["observations"][:2]:
        selected["tables"] = value["tables"]
        observer.capture_restituted_browser(role, original, root, checkpoint="ResaleReturned", resale=resale,
            posted_plan_id=value["posted_plan_id"], plan_digest=value["plan_digest"], observation=value["kind"], refusal=value["refusal"])
    selected["tables"] = observations["observations"][-1]["tables"]
    observer.verify_seeded_restituted_browser(role, custody_root=root, original=original, original_app_dsn="original")
    role.factory.settings.dsn = "restored"
    observer.verify_seeded_restituted_browser(role, custody_root=root, original=original, original_app_dsn="original")
    def document(path: Path) -> dict[str, Any]:
        return cast(dict[str, Any], observer.parse_json_document(path.read_text(encoding="utf-8"), reject_fractional_numbers=True))
    packet, observed, restored = (document(path) for path in (root / observer.PACKET,
        tmp_path / observer.OBSERVATIONS / observer.OBSERVATION_PACKET, root / observer.RESTORE))
    assert packet == expected and observed == observations
    assert independent.qualify_raw_cycle(packet)["status"] == "passed"
    assert independent.verify_raw_observations(packet, observed)["dependency_refusal_http_proven"]
    assert independent.verify_restored_cycle(packet, restored, observed)["populated_restore_proven"]


@pytest.mark.parametrize("attack", ["missing-packet", "foreign-original", "foreign-tenant", "extra-capture"])
def test_seeded_adapter_refuses_unbound_discovery_before_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str) -> None:
    root = tmp_path / observer.FAMILY
    current = state(monkeypatch)
    complete(root, current)
    if attack == "missing-packet":
        (root / observer.PACKET).unlink()
    elif attack == "extra-capture":
        (root / "checkpoint-4.json").write_text("{}", encoding="utf-8")
    else:
        packet = cast(dict[str, Any], observer.parse_json_document((root / observer.PACKET).read_text(encoding="utf-8"), reject_fractional_numbers=True))
        packet["tenant_id" if attack == "foreign-tenant" else "original_source_order_id"] = "foreign"
        (root / observer.PACKET).write_bytes(observer._bytes(packet, observer.MAX_PACKET_BYTES))
    def refused_query(*args: Any) -> Any:
        pytest.fail("Unbound packet must be refused before any database snapshot")
    monkeypatch.setattr(observer, "_snapshot", refused_query)
    with pytest.raises((ValueError, OSError)):
        observer.verify_seeded_restituted_browser(runtime(), custody_root=root, original="original", original_app_dsn="original")
