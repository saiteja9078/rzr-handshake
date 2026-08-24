"""Minimal MCP streamable-HTTP client used by the standalone demo agent."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class ACPClient:
    def __init__(self, endpoint: str = "http://127.0.0.1:8000/mcp") -> None:
        self.endpoint = endpoint.rstrip("/") + "/"

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ClientSession]:
        async with streamable_http_client(self.endpoint) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as client:
                await client.initialize()
                yield client

    @staticmethod
    def _result_value(result: Any) -> dict[str, Any]:
        structured = getattr(result, "structuredContent", None)
        if structured:
            return dict(structured)
        content = getattr(result, "content", []) or []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"text": text}
        return {}

    async def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self.session() as client:
            result = await client.call_tool(tool_name, arguments or {})
            return self._result_value(result)
