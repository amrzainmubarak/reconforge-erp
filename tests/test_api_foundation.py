from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reconforge import __version__
from reconforge.api import create_api_app
from reconforge.auth.policy import PolicyDecision, PolicyEvaluationContext
from reconforge.auth.policy_cache import PolicyDecisionCache
from reconforge.cli import app
from reconforge.db import run_migrations
from reconforge.db.migrations import MIGRATIONS
from reconforge.infrastructure.redis import RedisPolicyCacheVersionStore
from reconforge.platform.common import is_trusted_local_mode

runner = CliRunner()


def test_api_health_and_version_work_without_auth(tmp_path: Path) -> None:
    db_path = tmp_path / "api.db"
    run_migrations(db_path)
    client = TestClient(create_api_app(db_path))

    health = client.get("/api/v1/health")
    version = client.get("/api/v1/version")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["version"] == __version__
    assert health.json()["database"]["reachable"] is True
    assert health.json()["database"]["schema_version"] == MIGRATIONS[-1].version
    assert health.json()["database"]["path_summary"] == "api.db"
    assert version.status_code == 200
    assert version.json()["scope"] == "local/self-hosted foundation"
    assert health.headers["x-request-id"]
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "DENY"
    assert health.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert health.headers["X-Permitted-Cross-Domain-Policies"] == "none"


def test_protected_route_requires_auth_and_returns_structured_error(tmp_path: Path) -> None:
    db_path = tmp_path / "protected.db"
    run_migrations(db_path)
    client = TestClient(create_api_app(db_path))

    response = client.get("/api/v1/users")

    assert response.status_code == 401
    payload = response.json()
    assert set(payload["error"]) == {"code", "message", "request_id"}
    assert payload["error"]["code"] == "auth_required"
    assert "Traceback" not in response.text


def test_api_request_context_rejects_trusted_local_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "api-context.db"
    run_migrations(db_path)
    api = create_api_app(db_path)

    @api.get("/test-context")
    def context_probe() -> dict[str, bool]:
        return {"trusted_local": is_trusted_local_mode()}

    client = TestClient(api)
    response = client.get("/test-context")

    assert response.status_code == 200
    assert response.json() == {"trusted_local": False}
    assert is_trusted_local_mode() is True


def test_policy_cache_is_explicit_and_mutations_invalidate_it(tmp_path: Path) -> None:
    db_path = tmp_path / "policy-cache.db"
    run_migrations(db_path)
    default_api = create_api_app(db_path)
    assert default_api.state.policy_decision_cache is None

    api = create_api_app(db_path, policy_cache_enabled=True)
    cache = api.state.policy_decision_cache
    assert isinstance(cache, PolicyDecisionCache)
    context = PolicyEvaluationContext(
        user_id="operator",
        username="operator",
        user_permissions={"reports.read"},
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        authorized_tenant_ids=frozenset({"tenant-a"}),
        authorized_workspace_ids=frozenset({"workspace-a"}),
    )
    cache.evaluate(context, required_permission="reports.read", evaluator=_AllowedEvaluator())
    assert len(cache) == 1
    response = TestClient(api).post("/api/v1/auth/login", json={})
    assert response.status_code in {400, 401, 422}
    assert len(cache) == 0


def test_policy_cache_uses_shared_redis_generation_only_when_explicitly_configured(tmp_path: Path) -> None:
    db_path = tmp_path / "policy-cache-redis.db"
    run_migrations(db_path)
    local_api = create_api_app(db_path, policy_cache_enabled=True)
    assert local_api.state.policy_cache_version_store is None
    server_api = create_api_app(
        db_path,
        policy_cache_enabled=True,
        redis_url="redis://localhost:6379/0",
        redis_require_tls=False,
    )
    assert isinstance(server_api.state.policy_cache_version_store, RedisPolicyCacheVersionStore)
    assert isinstance(server_api.state.policy_decision_cache, PolicyDecisionCache)


class _AllowedEvaluator:
    def evaluate(self, context: PolicyEvaluationContext, **_: object) -> PolicyDecision:
        del context
        return PolicyDecision(True, "allowed", granted_permission="reports.read")

    def evaluate_any(self, context: PolicyEvaluationContext, **_: object) -> PolicyDecision:
        del context
        return PolicyDecision(True, "allowed", granted_permission="reports.read")


def test_api_serve_missing_db_fails_without_starting_server(tmp_path: Path) -> None:
    result = runner.invoke(app, ["api", "serve", "--db", str(tmp_path / "missing.db")])

    assert result.exit_code == 1
    assert "Run 'reconforge db init' first" in result.output
    assert "Traceback" not in result.output


def test_same_origin_web_root_is_host_bounded_and_security_header_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "hosted.db"
    run_migrations(db_path)
    web_root = tmp_path / "dist"
    (web_root / "assets").mkdir(parents=True)
    (web_root / "index.html").write_text("<!doctype html><title>ReconForge Studio</title>", encoding="utf-8")
    (web_root / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    client = TestClient(
        create_api_app(
            db_path,
            web_root=web_root,
            allowed_hosts=("reconforge.test",),
            secure_transport=True,
        ),
        base_url="https://reconforge.test",
    )

    spa = client.get("/admin-audit")
    health = client.get("/api/v1/health")
    asset = client.get("/assets/app.js")

    assert spa.status_code == health.status_code == asset.status_code == 200
    assert "ReconForge Studio" in spa.text
    assert health.headers["content-type"].startswith("application/json")
    assert asset.text == "export {};"
    assert spa.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    assert spa.headers["Content-Security-Policy"] == (
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; script-src 'self'; style-src 'self'; style-src-elem 'self'; "
        "style-src-attr 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
        "connect-src 'self'; manifest-src 'self'; worker-src 'self'; upgrade-insecure-requests"
    )
    assert client.get("/assets/missing.js").status_code == 404
    hostile = client.get("/", headers={"Host": "hostile.invalid"})
    assert hostile.status_code == 400
    assert hostile.headers["Content-Security-Policy"] == spa.headers["Content-Security-Policy"]
    assert hostile.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_api_serve_binds_direct_tls_web_root_and_exact_hosts(monkeypatch: Any, tmp_path: Path) -> None:
    db_path = tmp_path / "hosted-cli.db"
    run_migrations(db_path)
    web_root = tmp_path / "dist"
    web_root.mkdir()
    (web_root / "index.html").write_text("<!doctype html>", encoding="utf-8")
    certificate = tmp_path / "tls.pem"
    private_key = tmp_path / "tls-key.pem"
    certificate.write_text("synthetic certificate path fixture", encoding="utf-8")
    private_key.write_text("synthetic key path fixture", encoding="utf-8")
    captured: dict[str, object] = {}

    def run(application: Any, **kwargs: object) -> None:
        captured["application"] = application
        captured["kwargs"] = kwargs

    monkeypatch.setattr("reconforge.cli.uvicorn.run", run)
    result = runner.invoke(
        app,
        [
            "api", "serve", "--db", str(db_path), "--web-root", str(web_root),
            "--allowed-host", "reconforge.test", "--tls-certfile", str(certificate),
            "--tls-keyfile", str(private_key),
        ],
    )

    assert result.exit_code == 0, result.output
    application = captured["application"]
    assert application.state.web_root == web_root.resolve()  # type: ignore[union-attr]
    assert application.state.allowed_hosts == ("reconforge.test",)  # type: ignore[union-attr]
    assert application.state.secure_transport is True  # type: ignore[union-attr]
    assert captured["kwargs"] == {
        "host": "127.0.0.1", "port": 8765, "log_level": "info",
        "ssl_certfile": str(certificate), "ssl_keyfile": str(private_key),
    }


def test_deployed_web_root_requires_host_and_complete_tls_pair(tmp_path: Path) -> None:
    db_path = tmp_path / "hosted-invalid.db"
    run_migrations(db_path)
    web_root = tmp_path / "dist"
    web_root.mkdir()
    (web_root / "index.html").write_text("<!doctype html>", encoding="utf-8")
    certificate = tmp_path / "tls.pem"
    certificate.write_text("synthetic certificate path fixture", encoding="utf-8")

    no_host = runner.invoke(app, ["api", "serve", "--db", str(db_path), "--web-root", str(web_root)])
    half_tls = runner.invoke(
        app,
        ["api", "serve", "--db", str(db_path), "--allowed-host", "reconforge.test", "--tls-certfile", str(certificate)],
    )

    assert no_host.exit_code == half_tls.exit_code == 1
    assert "requires at least one exact --allowed-host" in no_host.output
    assert "certificate and key must be configured together" in half_tls.output


def test_api_serve_rejects_unallowlisted_otlp_before_server_start(monkeypatch: Any, tmp_path: Path) -> None:
    db_path = tmp_path / "otlp-invalid.db"
    run_migrations(db_path)
    started = False

    def run(*args: object, **kwargs: object) -> None:
        nonlocal started
        started = True

    monkeypatch.setattr("reconforge.cli.uvicorn.run", run)
    result = runner.invoke(
        app, ["api", "serve", "--db", str(db_path), "--otlp-http-endpoint", "https://collector.example:4318"]
    )
    assert result.exit_code == 1
    assert "not explicitly allowlisted" in result.output
    assert started is False


def test_host_allowlist_rejects_wildcards_schemes_paths_and_ambiguous_names(tmp_path: Path) -> None:
    db_path = tmp_path / "host-validation.db"
    run_migrations(db_path)

    for hostile in ("*", "*.example.com", "https://example.com", "example.com/path", "example..com"):
        try:
            create_api_app(db_path, allowed_hosts=(hostile,))
        except ValueError as exc:
            assert str(exc) == "allowed_hosts must contain exact DNS names or IPv4 addresses only."
        else:
            raise AssertionError(f"host allowlist accepted {hostile!r}")


def test_same_origin_deployment_docs_are_in_source_distribution_and_keep_claim_boundary() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    adr = Path("docs/adr/0200-studio-and-api-share-one-host-bounded-https-origin.md").read_text(
        encoding="utf-8"
    )
    runbook = Path("docs/operations/same-origin-browser-hosting.md").read_text(encoding="utf-8")

    assert "include docs/adr/0200-studio-and-api-share-one-host-bounded-https-origin.md" in manifest
    assert "include docs/operations/same-origin-browser-hosting.md" in manifest
    assert "include docs/security/deployment-boundaries.md" in manifest
    assert "not internet-facing or Enterprise-readiness assurance" in " ".join(adr.split())
    assert "does not certify an internet-facing topology" in " ".join(runbook.split())
