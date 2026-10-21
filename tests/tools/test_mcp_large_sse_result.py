"""Real SDK sessions retain tool results inside Hermes's existing wire budget."""

import json

import anyio
import httpx2
import pytest
from mcp import ClientSession

from tools.mcp_tool import MCPServerTask


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
async def test_large_tool_result_survives_sdk_event_decoding(monkeypatch, transport):
    text = "evidence " * 150_000  # Above the SDK's 1 MiB default, below Hermes's wire cap.
    send, receive = anyio.create_memory_object_stream(8)

    class EventStream(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b"event: endpoint\ndata: /messages?sessionId=test\n\n"
            async with receive:
                async for event in receive:
                    yield event

    async def handle(request):
        if request.method == "GET":
            if transport == "sse":
                return httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=EventStream())
            return httpx2.Response(405)
        if request.method == "DELETE":
            return httpx2.Response(200)
        message = json.loads(request.content)
        if "id" not in message:
            return httpx2.Response(202)
        if message["method"] == "initialize":
            result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities": {},
                      "serverInfo": {"name": "large-evidence", "version": "1"}}
        elif message["method"] == "tools/list":
            result = {"tools": [{"name": "evidence", "inputSchema": {"type": "object"}}]}
        else:
            result = {"content": [{"type": "text", "text": text}]}
        response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        event = ("event: message\ndata: " + json.dumps(response) + "\n\n").encode()
        if transport == "sse":
            await send.send(event)
            return httpx2.Response(202)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=event)

    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", lambda **kwargs: httpx2.MockTransport(handle))
    monkeypatch.setattr("tools.mcp_tool_transport._mcp_proxy_mounts", lambda *args: None)
    task = MCPServerTask("large-evidence")
    arguments = ("http://localhost/mcp", {}, 5.0, True, None, None, False)
    context = (task._sse_transport(*arguments) if transport == "sse" else
               task._streamable_http_transport(*arguments, set()))
    async with context as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            result = await session.call_tool("evidence", {})
            assert result.is_error is not True
            assert result.content[0].text == text
