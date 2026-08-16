"""Application entry: TCP/TLS SUPLA server + HTTP control API."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from aiohttp import web

from .consts import (
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
    DEFAULT_TCP_HOST,
    DEFAULT_TCP_PORT,
    DEFAULT_TLS_PORT,
)
from .http_api import create_app
from .registry import DeviceRegistry
from .tcp_server import SuplaTcpServer
from .tls import DEFAULT_CERT_DIR, load_or_create_ssl_context

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local SUPLA device server")
    parser.add_argument("--tcp-host", default=DEFAULT_TCP_HOST)
    parser.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT)
    parser.add_argument(
        "--tls-port",
        type=int,
        default=DEFAULT_TLS_PORT,
        help=f"TLS listen port (default {DEFAULT_TLS_PORT}; use 0 to disable)",
    )
    parser.add_argument(
        "--tls-cert",
        type=Path,
        default=None,
        help="PEM certificate path (default: auto-generated self-signed)",
    )
    parser.add_argument(
        "--tls-key",
        type=Path,
        default=None,
        help="PEM private key path (default: auto-generated self-signed)",
    )
    parser.add_argument(
        "--tls-cert-dir",
        type=Path,
        default=DEFAULT_CERT_DIR,
        help=f"Directory for auto-generated certs (default: {DEFAULT_CERT_DIR})",
    )
    parser.add_argument("--http-host", default=DEFAULT_HTTP_HOST)
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v, -vv)",
    )
    return parser


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def run_server(
    *,
    tcp_host: str = DEFAULT_TCP_HOST,
    tcp_port: int = DEFAULT_TCP_PORT,
    tls_port: int | None = DEFAULT_TLS_PORT,
    tls_cert: Path | None = None,
    tls_key: Path | None = None,
    tls_cert_dir: Path | None = None,
    http_host: str = DEFAULT_HTTP_HOST,
    http_port: int = DEFAULT_HTTP_PORT,
) -> None:
    registry = DeviceRegistry()

    ssl_context = None
    effective_tls_port: int | None = tls_port
    if effective_tls_port == 0:
        effective_tls_port = None
    if effective_tls_port is not None:
        ssl_context = load_or_create_ssl_context(
            certfile=tls_cert,
            keyfile=tls_key,
            cert_dir=tls_cert_dir,
        )

    tcp = SuplaTcpServer(
        registry,
        host=tcp_host,
        port=tcp_port,
        tls_port=effective_tls_port,
        ssl_context=ssl_context,
    )
    app = create_app(registry)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=http_host, port=http_port)

    await tcp.start()
    await site.start()
    logger.info("HTTP control API on http://%s:%s", http_host, http_port)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("shutting down...")
        await tcp.stop()
        await runner.cleanup()


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    try:
        asyncio.run(
            run_server(
                tcp_host=args.tcp_host,
                tcp_port=args.tcp_port,
                tls_port=args.tls_port,
                tls_cert=args.tls_cert,
                tls_key=args.tls_key,
                tls_cert_dir=args.tls_cert_dir,
                http_host=args.http_host,
                http_port=args.http_port,
            )
        )
    except KeyboardInterrupt:
        pass
