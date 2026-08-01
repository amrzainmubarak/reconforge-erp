from __future__ import annotations

import http.client
import socket
import ssl
import threading
import time
from pathlib import Path

import uvicorn

from reconforge.api import create_api_app
from reconforge.db import run_migrations
from tests.https_runtime import create_localhost_certificate


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def test_real_https_serves_spa_and_api_from_one_host_with_enforced_headers(tmp_path: Path) -> None:
    db_path = tmp_path / "https.db"
    run_migrations(db_path)
    web_root = tmp_path / "dist"
    (web_root / "assets").mkdir(parents=True)
    (web_root / "index.html").write_text("<!doctype html><title>Hosted ReconForge</title>", encoding="utf-8")
    (web_root / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    certificate, key = create_localhost_certificate(tmp_path)
    port = _free_port()
    application = create_api_app(
        db_path,
        web_root=web_root,
        allowed_hosts=("localhost",),
        secure_transport=True,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            ssl_certfile=str(certificate),
            ssl_keyfile=str(key),
            log_level="warning",
        )
    )
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    context = ssl.create_default_context(cafile=str(certificate))

    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started

        connection = http.client.HTTPSConnection("localhost", port, context=context, timeout=5)
        connection.request("GET", "/admin-audit")
        spa = connection.getresponse()
        spa_body = spa.read().decode("utf-8")
        tls_version = connection.sock.version() if connection.sock is not None else None
        assert spa.status == 200 and "Hosted ReconForge" in spa_body
        assert tls_version in {"TLSv1.2", "TLSv1.3"}
        assert spa.getheader("strict-transport-security") == "max-age=31536000; includeSubDomains"
        assert "script-src 'self'" in str(spa.getheader("content-security-policy"))
        connection.close()

        api = http.client.HTTPSConnection("localhost", port, context=context, timeout=5)
        api.request("GET", "/api/v1/health")
        health = api.getresponse()
        assert health.status == 200
        assert health.getheader("content-type", "").startswith("application/json")
        health.read()
        api.close()

        hostile = http.client.HTTPSConnection("localhost", port, context=context, timeout=5)
        hostile.request("GET", "/", headers={"Host": "hostile.invalid"})
        rejected = hostile.getresponse()
        assert rejected.status == 400
        rejected.read()
        hostile.close()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        assert not worker.is_alive()
