"""Portable remote MCP authentication reaches the existing native HTTP transport."""

import asyncio
from contextlib import asynccontextmanager
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_cli.agent_plugins import MCP_SCHEMA_V1, PLUGIN_SCHEMA_V1, load_agent_plugin


@pytest.fixture
def portable_plugin(tmp_path, monkeypatch):
    from hermes_cli import plugins

    home = tmp_path / "home"
    root = home / "plugins" / "portable"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({
        "$schema": PLUGIN_SCHEMA_V1, "name": "portable.test",
    }), encoding="utf-8")
    (home / "config.yaml").write_text(
        "plugins:\n  enabled: [portable.test]\n", encoding="utf-8",
    )
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setattr(plugins, "_plugin_manager", None)
    return root


@pytest.mark.parametrize("auth", [{}, {"auth": "oauth"}])
def test_portable_auth_reaches_native_http_client(portable_plugin, monkeypatch, auth):
    from hermes_cli.plugin_validate import validate_plugin_dir
    from tools import mcp_oauth_manager, mcp_tool
    from tools.mcp_tool_config import _load_mcp_config

    url = "https://example.test/mcp"
    (portable_plugin / "mcp.json").write_text(json.dumps({
        "$schema": MCP_SCHEMA_V1,
        "mcpServers": {"remote": {
            "type": "streamable-http", "url": url,
            "headers": {"X-Tenant": "public-tenant"}, **auth,
        }},
    }), encoding="utf-8")
    report = validate_plugin_dir(portable_plugin)
    assert report.ok, report.failures
    config = _load_mcp_config()["remote"]
    assert config.get("auth") == auth.get("auth")

    mcp_tool._ensure_mcp_sdk()
    provider = mcp_tool.sdk_httpx().Auth()
    manager = MagicMock()
    manager.get_or_build_provider.return_value = provider
    monkeypatch.setattr(mcp_oauth_manager, "get_manager", lambda: manager)
    captured = []

    @asynccontextmanager
    async def streams(endpoint, *, http_client, max_sse_event_size):
        assert endpoint == url
        assert http_client.headers["X-Tenant"] == "public-tenant"
        captured.append(http_client.auth)
        yield (None, None)

    async def serve(transport, label, timeout):
        async with transport:
            return "shutdown"

    monkeypatch.setattr(mcp_tool, "streamable_http_client", streams)
    server = mcp_tool.MCPServerTask("remote")
    monkeypatch.setattr(server, "_preflight_content_type", AsyncMock())
    monkeypatch.setattr(server, "_serve_transport", serve)

    async def connect():
        assert await server._prepare_run(config)
        assert await server._run_http(config) == "shutdown"

    asyncio.run(connect())
    assert config["strict_redirect_headers"] is True
    assert captured == [provider if auth else None]
    if auth:
        manager.get_or_build_provider.assert_called_once_with("remote", url, None)
    else:
        manager.get_or_build_provider.assert_not_called()


@pytest.mark.parametrize("extra", [
    {"auth": value} for value in (None, "", "OAuth", "bearer", True, {}, ["oauth"])
] + [{"auth": "oauth", "oauth": {"client_secret": "not-a-manifest-secret"}}])
def test_portable_remote_rejects_unsupported_auth_without_losing_siblings(portable_plugin, extra):
    (portable_plugin / "mcp.json").write_text(json.dumps({
        "$schema": MCP_SCHEMA_V1,
        "mcpServers": {
            "remote": {"type": "streamable-http", "url": "https://example.test/mcp", **extra},
            "worker": {"type": "stdio", "command": "python"},
        },
    }), encoding="utf-8")

    package = load_agent_plugin(portable_plugin, portable_plugin.parent / "data")

    assert set(package.mcp_servers) == {"worker"}
    assert [diagnostic.scope for diagnostic in package.diagnostics] == ["mcp:remote"]
