"""TLS helpers for SUPLA port 2016."""

from __future__ import annotations

import ipaddress
import logging
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

logger = logging.getLogger(__name__)

DEFAULT_CERT_DIR = Path.home() / ".cache" / "supla-hacs"
DEFAULT_CERT_FILE = "server.crt"
DEFAULT_KEY_FILE = "server.key"


def create_server_ssl_context(certfile: Path, keyfile: Path) -> ssl.SSLContext:
    """Build a TLS server context suitable for SUPLA devices."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # Older commercial devices such as the Zamel ROW-02 use TLS 1.1 and
    # static-RSA AES-CBC suites. Keep modern suites enabled while allowing
    # that legacy profile; RC4 remains unavailable in OpenSSL's defaults.
    ctx.minimum_version = ssl.TLSVersion.TLSv1_1
    # OpenSSL 3 requires security level 0 for TLS 1.1's SHA-1 handshake.
    # Restrict the legacy additions to AES-CBC; do not enable the RC4 suites
    # also advertised by these devices.
    ctx.set_ciphers("DEFAULT:AES128-SHA:AES256-SHA:!RC4:@SECLEVEL=0")
    ctx.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
    return ctx


def ensure_certificate(
    cert_dir: Path | None = None,
    *,
    cert_file: str = DEFAULT_CERT_FILE,
    key_file: str = DEFAULT_KEY_FILE,
    common_name: str = "supla-local",
) -> tuple[Path, Path]:
    """
    Return (cert_path, key_path), generating a self-signed cert if missing.

    Matches the openhab-supla / jSupla approach: auto self-signed for local use.
    Commercial devices usually need security_level=INSECURE (skip CA) for this.
    """
    directory = cert_dir or DEFAULT_CERT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    cert_path = directory / cert_file
    key_path = directory / key_file

    if cert_path.is_file() and key_path.is_file():
        logger.info("Using TLS certificate %s", cert_path)
        return cert_path, key_path

    logger.info("Generating self-signed TLS certificate in %s", directory)
    _generate_self_signed(cert_path, key_path, common_name=common_name)
    return cert_path, key_path


def load_or_create_ssl_context(
    *,
    certfile: Path | None = None,
    keyfile: Path | None = None,
    cert_dir: Path | None = None,
) -> ssl.SSLContext:
    if certfile is not None or keyfile is not None:
        if certfile is None or keyfile is None:
            raise ValueError("both --tls-cert and --tls-key are required")
        if not certfile.is_file() or not keyfile.is_file():
            raise FileNotFoundError(f"TLS cert/key not found: {certfile}, {keyfile}")
        return create_server_ssl_context(certfile, keyfile)

    cert_path, key_path = ensure_certificate(cert_dir)
    return create_server_ssl_context(cert_path, key_path)


def _generate_self_signed(cert_path: Path, key_path: Path, *, common_name: str) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "supla-hacs"),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName(common_name),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.chmod(0o600)
    cert_path.chmod(0o644)
