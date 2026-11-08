"""Explicit CLI authorization resolves enabled portable MCPs without taking ownership."""

import argparse
import asyncio
import json
from pathlib import Path

import pytest

from hermes_cli import mcp_config
from hermes_cli.agent_plugins import MCP_SCHEMA_V1, PLUGIN_SCHEMA_V1
from hermes_cli.config import save_config
from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override
from tools.mcp_oauth import HermesTokenStorage, _is_interactive


def seed_plugin(home: Path, *, auth=True, enabled=True, native=None):
    root = home / "plugins" / "portable"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({
        "$schema": PLUGIN_SCHEMA_V1, "name": "portable.test",
    }), encoding="utf-8")
    (root / "mcp.json").write_text(json.dumps({
        "$schema": MCP_SCHEMA_V1,
        "mcpServers": {"remote": {"type": "streamable-http", "url": f"https://{home.name}.example/mcp",
                                  **({"auth": "oauth"} if auth else {})}},
    }), encoding="utf-8")
    token = set_hermes_home_override(home)
    try:
        save_config({"plugins": {"enabled": ["portable.test"], "disabled": [] if enabled else ["portable.test"]},
                     **({"mcp_servers": native} if native else {})})
    finally:
        reset_hermes_home_override(token)
    return root


@pytest.fixture
def probe(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    seen = []

    def complete(name, cfg, connect_timeout):
        from mcp.shared.auth import OAuthToken

        assert _is_interactive()
        assert connect_timeout >= 300
        home = get_hermes_home()
        seen.append((home, name, cfg))
        asyncio.run(HermesTokenStorage(name).set_tokens(OAuthToken(
            access_token=f"test-token-{home.name}", token_type="Bearer",
        )))
        return [("read", "Read an example")]

    monkeypatch.setattr(mcp_config, "_probe_single_server", complete)
    return seen


@pytest.mark.parametrize("command", [mcp_config.cmd_mcp_login, mcp_config.cmd_mcp_reauth])
def test_named_auth_uses_portable_source_without_writing_config(tmp_path, capsys, probe, command):
    home = tmp_path / "alpha"
    root = seed_plugin(home)
    before = {path: path.read_bytes() for path in (home / "config.yaml", root / "plugin.json", root / "mcp.json")}
    token = set_hermes_home_override(home)
    try:
        command(argparse.Namespace(name="remote", all=False, flow=None))
        assert HermesTokenStorage("remote").has_cached_tokens()
    finally:
        reset_hermes_home_override(token)

    assert [(owner, name, cfg["url"], cfg["auth"], cfg["strict_redirect_headers"])
            for owner, name, cfg in probe] == [(home, "remote", "https://alpha.example/mcp", "oauth", True)]
    assert "Authenticated" in capsys.readouterr().out
    assert all(path.read_bytes() == contents for path, contents in before.items())


@pytest.mark.parametrize("case", ["absent", "disabled", "non-oauth", "native-non-oauth"])
def test_named_auth_refuses_unavailable_or_non_oauth_sources(tmp_path, capsys, probe, case):
    home = tmp_path / "alpha"
    seed_plugin(home, auth=case != "non-oauth", enabled=case != "disabled",
                native={"remote": {"url": "https://native.example/mcp"}} if case == "native-non-oauth" else None)
    token = set_hermes_home_override(home)
    try:
        mcp_config.cmd_mcp_login(argparse.Namespace(name="missing" if case == "absent" else "remote", flow=None))
    finally:
        reset_hermes_home_override(token)

    assert probe == []
    message = "not configured for OAuth" if "oauth" in case else "not found"
    assert message in capsys.readouterr().out
    assert not (home / "mcp-tokens").exists()


def test_portable_login_keeps_profile_credentials_separate(tmp_path, probe):
    homes = [tmp_path / "alpha", tmp_path / "beta"]
    for home in homes:
        seed_plugin(home)
    for home in homes:
        token = set_hermes_home_override(home)
        try:
            mcp_config.cmd_mcp_login(argparse.Namespace(name="remote", flow=None))
        finally:
            reset_hermes_home_override(token)

    assert [(home, cfg["url"]) for home, _, cfg in probe] == [
        (home, f"https://{home.name}.example/mcp") for home in homes
    ]
    for home in homes:
        stored = json.loads((home / "mcp-tokens" / "remote.json").read_text(encoding="utf-8"))
        assert stored["access_token"] == f"test-token-{home.name}"


def test_portable_auth_does_not_expand_bulk_or_remove_ownership(tmp_path, capsys, probe):
    home = tmp_path / "alpha"
    seed_plugin(home)
    before = (home / "config.yaml").read_bytes()
    token = set_hermes_home_override(home)
    try:
        mcp_config.cmd_mcp_reauth(argparse.Namespace(name=None, all=True))
        mcp_config.cmd_mcp_remove(argparse.Namespace(name="remote"))
    finally:
        reset_hermes_home_override(token)

    assert probe == []
    assert "not found" in capsys.readouterr().out
    assert (home / "config.yaml").read_bytes() == before
