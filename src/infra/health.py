"""Tiny health endpoint for container checks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable


class HealthServer:
    def __init__(self, host: str, port: int, is_ready: Callable[[], bool]) -> None:
        self._host = host
        self._port = port
        self._is_ready = is_ready
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.read(1024)
            if self._is_ready():
                body = b"ok"
                status = b"200 OK"
            else:
                body = b"not ready"
                status = b"503 Service Unavailable"
            response = (
                b"HTTP/1.1 "
                + status
                + b"\r\nContent-Type: text/plain\r\nContent-Length: "
                + str(len(body)).encode("ascii")
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
