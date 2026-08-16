#!/usr/bin/env python3
"""Forward SUPLA device ports to another host on the LAN.

Point this at the machine running the real server and let it listen on 2015 and
2016 locally. Devices already configured for this machine keep connecting here
and end up talking to the other host, so you can move the server around without
reconfiguring every device.

The forwarding is byte-for-byte at the TCP layer, so port 2016 keeps working
untouched: the TLS session is negotiated end to end between the device and the
real server, and this process never sees the plaintext or needs a certificate.

    python3 tools/supla_proxy.py 192.168.1.10
    python3 tools/supla_proxy.py 192.168.1.10 --port 2015 --port 2016
    python3 tools/supla_proxy.py homeassistant.local --port 2015:12015

Only the standard library is used, so any Python 3.9 or newer will run it.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys

DEFAULT_PORTS = (2015, 2016)
BUFFER_SIZE = 65536

logger = logging.getLogger("supla-proxy")


class PortForwarder:
    """One listening port, relayed to one port on the target host."""

    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        target_host: str,
        target_port: int,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self._server: asyncio.AbstractServer | None = None
        self._connections: set[asyncio.Task] = set()
        self._counter = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._on_client, host=self.listen_host, port=self.listen_port
        )
        logger.info(
            "listening on %s:%d -> %s:%d",
            self.listen_host,
            self.listen_port,
            self.target_host,
            self.target_port,
        )

    @property
    def bound_port(self) -> int:
        """The port actually being listened on, which differs if 0 was asked for."""
        if self._server is None or not self._server.sockets:
            return self.listen_port
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()

        # Relays first: since Python 3.12.1 wait_closed() also waits for every
        # open connection, so closing them afterwards would never return.
        for task in list(self._connections):
            task.cancel()
        if self._connections:
            await asyncio.gather(*self._connections, return_exceptions=True)
            self._connections.clear()

        if self._server is not None:
            await self._server.wait_closed()
            self._server = None

    async def _on_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._counter += 1
        task = asyncio.get_running_loop().create_task(
            self._relay(self._counter, reader, writer)
        )
        self._connections.add(task)
        task.add_done_callback(self._connections.discard)

    async def _relay(
        self,
        conn_id: int,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        peer = _describe(client_writer)
        label = "#%d %s" % (conn_id, peer)
        try:
            server_reader, server_writer = await asyncio.open_connection(
                self.target_host, self.target_port
            )
        except OSError as err:
            logger.warning(
                "%s: cannot reach %s:%d (%s)",
                label,
                self.target_host,
                self.target_port,
                err,
            )
            await _close(client_writer)
            return

        logger.info(
            "%s connected via :%d -> %s:%d",
            label,
            self.listen_port,
            self.target_host,
            self.target_port,
        )
        up = _Counter()
        down = _Counter()
        try:
            await asyncio.gather(
                _pump(client_reader, server_writer, up),
                _pump(server_reader, client_writer, down),
            )
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - one connection must not stop the proxy
            logger.debug("%s relay ended: %s", label, err)
        finally:
            await _close(server_writer)
            await _close(client_writer)
            logger.info(
                "%s closed, %s up / %s down", label, _size(up.total), _size(down.total)
            )


class _Counter:
    __slots__ = ("total",)

    def __init__(self) -> None:
        self.total = 0


async def _pump(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, counter: _Counter
) -> None:
    """Copy one direction until it ends, then half-close the far side."""
    try:
        while True:
            chunk = await reader.read(BUFFER_SIZE)
            if not chunk:
                break
            counter.total += len(chunk)
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, OSError):
        return
    # The peer stopped sending; let the other end see the same, so a clean
    # shutdown on one side is not reported as a broken connection on the other.
    with contextlib.suppress(OSError, NotImplementedError):
        if writer.can_write_eof():
            writer.write_eof()


async def _close(writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(OSError):
        writer.close()
    with contextlib.suppress(OSError, asyncio.CancelledError):
        await writer.wait_closed()


def _describe(writer: asyncio.StreamWriter) -> str:
    peer = writer.get_extra_info("peername")
    if isinstance(peer, tuple) and len(peer) >= 2:
        return "%s:%s" % (peer[0], peer[1])
    return str(peer)


def _size(count: int) -> str:
    if count < 1024:
        return "%d B" % count
    if count < 1024 * 1024:
        return "%.1f kB" % (count / 1024)
    return "%.1f MB" % (count / (1024 * 1024))


def parse_port(value: str) -> tuple[int, int]:
    """"2015" -> (2015, 2015); "2015:12015" -> listen 2015, forward to 12015."""
    listen, _, target = value.partition(":")
    try:
        listen_port = int(listen)
        target_port = int(target) if target else listen_port
    except ValueError:
        raise argparse.ArgumentTypeError(
            "expected PORT or LISTEN:TARGET, got %r" % value
        ) from None
    for port in (listen_port, target_port):
        if not 1 <= port <= 65535:
            raise argparse.ArgumentTypeError("port out of range: %d" % port)
    return listen_port, target_port


async def run(
    target_host: str, ports: list[tuple[int, int]], listen_host: str
) -> int:
    forwarders = [
        PortForwarder(listen_host, listen_port, target_host, target_port)
        for listen_port, target_port in ports
    ]

    started: list[PortForwarder] = []
    try:
        for forwarder in forwarders:
            await forwarder.start()
            started.append(forwarder)
    except OSError as err:
        logger.error("cannot listen: %s", err)
        for forwarder in started:
            await forwarder.stop()
        return 1

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    logger.info("forwarding to %s, press Ctrl+C to stop", target_host)
    try:
        await stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("shutting down")
        for forwarder in started:
            await forwarder.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forward SUPLA device ports to another host on the LAN.",
        epilog="TLS on 2016 passes through untouched; no certificate is needed here.",
    )
    parser.add_argument(
        "target", help="host running the real SUPLA server (IP or hostname)"
    )
    parser.add_argument(
        "-p",
        "--port",
        dest="ports",
        action="append",
        type=parse_port,
        metavar="PORT[:TARGET]",
        help="port to forward, repeatable (default: 2015 and 2016)",
    )
    parser.add_argument(
        "-l",
        "--listen",
        default="0.0.0.0",
        help="address to listen on (default: all interfaces)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log every relay detail"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    ports = args.ports or [(port, port) for port in DEFAULT_PORTS]
    try:
        return asyncio.run(run(args.target, ports, args.listen))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
