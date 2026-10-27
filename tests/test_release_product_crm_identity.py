"""Community CRM author provenance never infers identity from reused display names."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.domain.crm_contracts import CustomerQuotation, QuotationLineItem
from reconforge.infrastructure.sqlite_crm_contracts import SqliteCRMContractsRepository

PASSWORD = "Synthetic-CRM-Identity-2026!"


def test_sqlite_author_provenance_survives_rename_and_refuses_legacy_takeover(tmp_path: Path) -> None:
    database = tmp_path / "crm.db"
    run_migrations(database)
    connection = connect(database)
    try:
        auth = LocalAuthService(connection)
        creator = auth.init_admin(username="creator-name", password=PASSWORD)
        reviewer = auth.create_user(username="reviewer-name", password=PASSWORD, role="admin")
        admin_role = connection.execute("SELECT id FROM roles WHERE name='admin'").fetchone()[0]
        for permission in ("sales.manage", "sales.approve"):
            connection.execute("INSERT OR IGNORE INTO permissions(name,description) VALUES(?,?)", (permission, "Synthetic CRM identity acceptance grant"))
            connection.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_name) VALUES(?,?)", (admin_role, permission))
        connection.commit()
        repository = SqliteCRMContractsRepository(connection)
        repository.save_quotation(CustomerQuotation("Q-LEGACY", "OP-SOURCE", "default", "CUSTOMER", "USD", "2026-12-31", creator.username, "draft", (QuotationLineItem(1, "SERVICE", "Synthetic legacy service", 1, 1001),)))
    finally:
        connection.close()
    client = TestClient(create_api_app(database))
    login = client.post("/api/v1/auth/login", json={"username": "creator-name", "password": PASSWORD})
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    quote_path = "/api/v1/crm/contracts/quotations"
    payload = {"quote_id": "Q-CANONICAL", "opportunity_id": "OP-SOURCE", "customer_id": "CUSTOMER", "currency": "USD", "valid_until": "2026-12-31", "lines": [{"line_number": 1, "item_id": "SERVICE", "description": "Synthetic service", "quantity": 1, "unit_price_minor": 1001}]}
    created = client.post(quote_path, headers=headers, json=payload)
    assert created.status_code == 200, created.text
    assert client.get(quote_path + "/Q-CANONICAL", headers=headers).json()["submitter_user_id"] == creator.id
    connection = connect(database)
    try:
        connection.execute("UPDATE users SET username='creator-renamed' WHERE id=?", (creator.id,))
        connection.commit()
        LocalAuthService(connection).create_user(username="creator-name", password=PASSWORD, role="admin")
    finally:
        connection.close()
    self_approval = client.post(quote_path + "/Q-CANONICAL/approve", headers=headers, json={"approver_role": "admin"})
    assert self_approval.status_code == 400 and self_approval.json()["error"]["code"] == "crm_sod_violation"
    legacy = client.post(quote_path + "/Q-LEGACY/approve", headers=headers, json={"approver_role": "admin"})
    assert legacy.status_code == 409 and legacy.json()["error"]["code"] == "quotation_identity_unverified"
    duplicate = client.post(quote_path, headers=headers, json={**payload, "quote_id": "Q-LEGACY", "lines": [{**payload["lines"][0], "unit_price_minor": 9999}]})
    assert duplicate.status_code == 409
    assert client.get(quote_path + "/Q-LEGACY", headers=headers).json()["total_net_minor"] == 1001
    reviewer_login = client.post("/api/v1/auth/login", json={"username": "reviewer-name", "password": PASSWORD})
    assert reviewer_login.status_code == 200, reviewer_login.text
    reviewer_headers = {"Authorization": "Bearer " + reviewer_login.json()["access_token"]}
    approved = client.post(quote_path + "/Q-CANONICAL/approve", headers=reviewer_headers, json={"approver_role": "admin"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_by_user_id"] == reviewer.id
    duplicate_approved = client.post(quote_path, headers=reviewer_headers, json={**payload, "lines": [{**payload["lines"][0], "unit_price_minor": 9999}]})
    assert duplicate_approved.status_code == 409
    retained = client.get(quote_path + "/Q-CANONICAL", headers=reviewer_headers).json()
    assert retained["status"] == "approved" and retained["total_net_minor"] == 1001 and retained["submitter_user_id"] == creator.id and retained["approved_by_user_id"] == reviewer.id
    connection = connect(database)
    try:
        repository = SqliteCRMContractsRepository(connection)
        assert repository.quotation_author_id("default", "Q-CANONICAL") == creator.id
        assert repository.quotation_author_id("default", "Q-LEGACY") is None
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE crm_quotation_authorities SET user_id=? WHERE quote_id='Q-CANONICAL'", (reviewer.id,))
        assert repository.quotation_author_id("default", "Q-CANONICAL") == creator.id
    finally:
        connection.close()
