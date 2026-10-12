"""Restore probes must target visible IC1 rows through the real owner context."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tests import intercompany_operations_browser_seed as helper


class Connection:
    def __init__(self, counts):
        self.counts = counts
        self.table = ""

    def execute(self, statement, parameters):
        assert parameters == ("tenant",)
        self.table = next(name for name in self.counts if "reconforge." + name in statement)
        return self

    def fetchall(self):
        return [{"id": "original"}] * self.counts[self.table]

    def fetchone(self):
        return {"n": self.counts[self.table]}


def setup_actor(monkeypatch, counts, *, denied=False):
    connection, actor, events = Connection(counts), object(), []

    class Repository:
        def get_source(self, source_id, *, actor):
            events.append(("current_owner_authorization", source_id, actor))
            if denied:
                raise PermissionError("Current group grant revoked")
            return {"closed": True, "plans": [{"phase": 2}] * 3}

    repository = Repository()

    class Runtime:
        def __init__(self, base):
            assert base.tenant == "tenant"

        @contextmanager
        def actor(self, name):
            events.append(("existing_three_book_actor", name))
            try:
                yield connection, repository, actor
            finally:
                events.append(("context_closed",))

    monkeypatch.setattr(helper, "IntercompanyRuntime", Runtime)
    return SimpleNamespace(tenant="tenant"), (connection, repository, actor), events


def test_restore_hook_uses_original_owner_actor_and_current_whole_source_authority(monkeypatch):
    base, expected, events = setup_actor(monkeypatch, {
        "intercompany_operation_sources": 1, "intercompany_operation_plans": 3, "intercompany_operation_links": 5})
    with helper.intercompany_restore_tamper_actor(base) as observed:
        assert observed == expected
        assert events == [("existing_three_book_actor", "browser-poster"), ("current_owner_authorization", "original", expected[2])]
    assert events[-1] == ("context_closed",)
    assert len(helper.INTERCOMPANY_RESTORE_TAMPER) == 3
    for table, statement in zip(("intercompany_operation_sources", "intercompany_operation_plans", "intercompany_operation_links"),
                                helper.INTERCOMPANY_RESTORE_TAMPER, strict=True):
        assert statement.startswith("UPDATE reconforge." + table) and "WHERE tenant_id=%s" in statement and statement.count("%s") == 1
    assert "kind='eliminate'" in helper.INTERCOMPANY_RESTORE_TAMPER[1]


@pytest.mark.parametrize("table,count", [("intercompany_operation_sources", 0), ("intercompany_operation_sources", 2),
                                        ("intercompany_operation_plans", 0), ("intercompany_operation_plans", 2),
                                        ("intercompany_operation_links", 0), ("intercompany_operation_links", 4)])
def test_zero_or_incomplete_target_population_never_becomes_a_tamper_probe(monkeypatch, table, count):
    counts = {"intercompany_operation_sources": 1, "intercompany_operation_plans": 3, "intercompany_operation_links": 5}
    counts[table] = count
    base, _, events = setup_actor(monkeypatch, counts)
    with pytest.raises(AssertionError, match="Restored tamper actor"), helper.intercompany_restore_tamper_actor(base):
        pytest.fail("Incomplete visible target population was admitted")
    assert events[-1] == ("context_closed",)


def test_current_parent_authority_refusal_is_not_replaced_by_raw_visible_rows(monkeypatch):
    base, _, events = setup_actor(monkeypatch, {
        "intercompany_operation_sources": 1, "intercompany_operation_plans": 3, "intercompany_operation_links": 5}, denied=True)
    with pytest.raises(PermissionError, match="group grant revoked"), helper.intercompany_restore_tamper_actor(base):
        pytest.fail("Revoked whole-source authority was admitted")
    assert events[-1] == ("context_closed",)
