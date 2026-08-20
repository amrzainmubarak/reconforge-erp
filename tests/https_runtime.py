from __future__ import annotations

import argparse
import ipaddress
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import uvicorn

pytest.importorskip("cryptography", reason="TLS certificate test runtime requires cryptography extra")

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from reconforge.api import create_api_app
from reconforge.db import run_migrations


def create_localhost_certificate(directory: Path) -> tuple[Path, Path]:
    """Create a short-lived synthetic certificate for localhost tests only."""

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_path = directory / "localhost-cert.pem"
    key_path = directory / "localhost-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, key_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="reconforge-https-runtime-") as raw_directory:
        directory = Path(raw_directory)
        certificate, key = create_localhost_certificate(directory)
        database = directory / "runtime.db"
        run_migrations(database)
        application = create_api_app(
            database,
            web_root=arguments.web_root,
            allowed_hosts=("localhost",),
            secure_transport=True,
        )
        uvicorn.run(
            application,
            host="127.0.0.1",
            port=arguments.port,
            ssl_certfile=str(certificate),
            ssl_keyfile=str(key),
            log_level="warning",
        )


if __name__ == "__main__":
    main()
