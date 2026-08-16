"""asyncio TCP/TLS listeners for SUPLA devices."""

from __future__ import annotations

import asyncio
import logging
import ssl

from .consts import DEFAULT_TCP_HOST, DEFAULT_TCP_PORT, DEFAULT_TLS_PORT
from .registry import DeviceRegistry
from .session import DeviceSession

logger = logging.getLogger(__name__)


class SuplaTcpServer:
    """Accepts plain (2015) and/or TLS (2016) SUPLA device connections."""

    def __init__(
        self,
        registry: DeviceRegistry,
        host: str = DEFAULT_TCP_HOST,
        port: int = DEFAULT_TCP_PORT,
        *,
        tls_port: int | None = DEFAULT_TLS_PORT,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.registry = registry
        self.host = host
        self.port = port
        self.tls_port = tls_port
        self.ssl_context = ssl_context
        self._servers: list[asyncio.Server] = []
        self._sessions: set[asyncio.Task[None]] = set()

    @property
    def servers(self) -> list[asyncio.Server]:
        return list(self._servers)

    async def start(self) -> None:
        plain = await asyncio.start_server(
            self._on_connection,
            host=self.host,
            port=self.port,
        )
        self._servers.append(plain)
        logger.info(
            "SUPLA plain TCP listening on %s",
            ", ".join(str(s.getsockname()) for s in (plain.sockets or [])),
        )

        if self.tls_port is not None:
            if self.ssl_context is None:
                raise ValueError("ssl_context is required when tls_port is set")
            tls = await asyncio.start_server(
                self._on_connection,
                host=self.host,
                port=self.tls_port,
                ssl=self.ssl_context,
            )
            self._servers.append(tls)
            logger.info(
                "SUPLA TLS listening on %s",
                ", ".join(str(s.getsockname()) for s in (tls.sockets or [])),
            )

    async def stop(self) -> None:
        for server in self._servers:
            server.close()

        # Live sessions have to go first: since Python 3.12.1 wait_closed()
        # also waits for every open connection, so a connected device would
        # otherwise hold the shutdown forever.
        tasks = list(self._sessions)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._sessions.clear()

        for server in self._servers:
            await server.wait_closed()
        self._servers.clear()
        logger.info("SUPLA device listeners stopped")

    async def _on_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        ssl_obj = writer.get_extra_info("ssl_context")
        transport_ssl = writer.get_extra_info("ssl_object")
        secure = transport_ssl is not None or ssl_obj is not None
        logger.debug("incoming %s connection from %s", "TLS" if secure else "plain", peer)

        session = DeviceSession(reader, writer, self.registry)
        task = asyncio.create_task(
            session.run(),
            name=f"supla-session-{'tls' if secure else 'tcp'}-{peer}",
        )
        self._sessions.add(task)

        def _done(t: asyncio.Task[None]) -> None:
            self._sessions.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.debug("session task ended with %s", t.exception())

        task.add_done_callback(_done)
