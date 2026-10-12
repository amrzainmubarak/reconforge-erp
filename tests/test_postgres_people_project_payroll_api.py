"""Actual secure-transport HTTP workforce commands using both native DB roles."""
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from tests.test_postgres_people_project_payroll import PeopleRuntime, approved_budget, approved_time

pytest_plugins = ("tests.test_postgres_people_project_payroll",)


def sessions(client: TestClient, runtime: PeopleRuntime) -> dict[str,dict[str,str]]:
    scope = {"X-ReconForge-Tenant":runtime.base.tenant,"X-ReconForge-Workspace":"work","X-ReconForge-Organization":"org","X-ReconForge-Legal-Entity":"entity"}
    result={}
    for name in ("maker","checker","poster"):
        response=client.post("/api/v1/auth/login",headers=scope,json={"username":name,"password":runtime.base.password})
        assert response.status_code==200
        result[name]={**scope,"Authorization":"Bearer "+response.json()["access_token"]}
        assert client.post("/api/v1/auth/step-up",headers=result[name],json={"password":runtime.base.password}).status_code==200
    return result


def application(runtime: PeopleRuntime, tmp_path: Path, *, private: bool=True) -> Any:
    return create_api_app(tmp_path/"local.db",tenant_db_root=tmp_path/"tenants",postgres_dsn=runtime.base.factory.settings.dsn,
        postgres_personnel_dsn=runtime.private.settings.dsn if private else None,postgres_require_tls=False,secure_transport=True)


def test_actual_https_accrual_partial_final_settlement_and_private_evidence(people: PeopleRuntime,tmp_path: Path) -> None:
    budget,times=approved_budget(people),approved_time(people)
    with TestClient(application(people,tmp_path),base_url="https://testserver") as client:
        headers=sessions(client,people)
        root="/api/v1/people-project-payroll"
        body={"command_id":"http-accrual","time_ids":times,"budget_id":budget["id"],"expected_budget_version":budget["row_version"],"period_id":"period","posting_date":"2026-10-04","journal_code":"STOCK","expense_account_code":"LABOR","liability_account_code":"WAGES","cash_account_code":"CASH"}
        response=client.post(root+"/payruns",headers=headers["maker"],json=body)
        assert response.status_code==200,response.text
        source=response.json()["plan"]
        assert source["amount_minor"]=="2501" and "private" not in source
        def post(plan: dict[str,Any],suffix: str) -> None:
            phase={"command_id":"http-review-"+suffix,"expected_plan_digest":plan["plan_digest"]}
            assert client.post(root+"/plans/"+plan["id"]+"/review",headers=headers["maker"],json=phase).status_code==403
            reviewed=client.post(root+"/plans/"+plan["id"]+"/review",headers=headers["checker"],json=phase)
            assert reviewed.status_code==200,reviewed.text
            phase["command_id"]="http-post-"+suffix
            assert client.post(root+"/plans/"+plan["id"]+"/post",headers=headers["checker"],json=phase).status_code==403
            posted=client.post(root+"/plans/"+plan["id"]+"/post",headers=headers["poster"],json=phase)
            assert posted.status_code==200,posted.text
            assert client.post(root+"/plans/"+plan["id"]+"/post",headers=headers["poster"],json=phase).json()==posted.json()
        post(source,"accrual")
        evidence=client.get(root+"/payruns/"+source["id"]+"/evidence",headers=headers["maker"])
        assert evidence.status_code==200,evidence.text
        employees=evidence.json()["payrun"]["private"]["employees"]
        first=next(row["employee_id"] for row in employees if row["gross_minor"]=="1502")
        second=next(row["employee_id"] for row in employees if row["gross_minor"]=="999")
        for suffix,allocations in (("partial",{first:"1000"}),("final",{first:"502",second:"999"})):
            payment=client.post(root+"/payruns/"+source["id"]+"/payments",headers=headers["maker"],json={"command_id":"http-"+suffix,"employees_minor":allocations,"period_id":"period","posting_date":"2026-10-05"})
            assert payment.status_code==200,payment.text
            post(payment.json()["plan"],suffix)
        evidence=client.get(root+"/payruns/"+source["id"]+"/evidence",headers=headers["maker"])
        assert evidence.status_code==200 and len(evidence.json()["native_effects"])==3
        assert client.get(root+"/plans/"+source["id"],headers=headers["maker"]).status_code==200
        assert "private" not in client.get(root+"/plans/"+source["id"],headers=headers["maker"]).json()["plan"]
        assert client.get(root+"/payruns/"+source["id"]+"/evidence",headers={**headers["maker"],"X-ReconForge-Workspace":"foreign"}).status_code==403


def test_missing_private_pool_is_explicit_unavailable_after_auth_admission(people: PeopleRuntime,tmp_path: Path) -> None:
    with TestClient(application(people,tmp_path,private=False),base_url="https://testserver") as client:
        headers=sessions(client,people)
        body={"command_id":"no-private","employee_code":"NATIVE","display_name":"Synthetic private"}
        response=client.post("/api/v1/people-project-payroll/employees",headers=headers["maker"],json=body)
        assert response.status_code==503
        assert response.json()["error"]["code"]=="personnel_backend_unavailable"
        assert client.post("/api/v1/people-project-payroll/employees",headers=headers["maker"],json={**body,"database_factory":"ordinary"}).status_code==422
