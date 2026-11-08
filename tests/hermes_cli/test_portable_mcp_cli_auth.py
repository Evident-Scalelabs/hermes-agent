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
            access_token=f"test-token-{home.name}-{len(seen)}", token_type="Bearer",
        )))
        return [("read", "Read an example")]

    monkeypatch.setattr(mcp_config, "_probe_single_server", complete)
    return seen


@pytest.mark.parametrize("case", ["login", "reauth", "profile-return"])
def test_named_auth_keeps_source_and_credentials_profile_scoped_without_config_writes(tmp_path, capsys, probe, case):
    homes = [tmp_path / "alpha"] + ([tmp_path / "beta"] if case == "profile-return" else [])
    before = {}
    for home in homes:
        root = seed_plugin(home)
        before.update({path: path.read_bytes() for path in (home / "config.yaml", root / "plugin.json", root / "mcp.json")})
    sequence = homes + [homes[0]] if case == "profile-return" else homes
    command = mcp_config.cmd_mcp_reauth if case == "reauth" else mcp_config.cmd_mcp_login
    expected_tokens = {}
    for attempt, home in enumerate(sequence, 1):
        token = set_hermes_home_override(home)
        try:
            command(argparse.Namespace(name="remote", all=False, flow=None))
            assert HermesTokenStorage("remote").has_cached_tokens()
        finally:
            reset_hermes_home_override(token)
        expected_tokens[home] = f"test-token-{home.name}-{attempt}"
        for owner, expected in expected_tokens.items():
            stored = json.loads((owner / "mcp-tokens" / "remote.json").read_text(encoding="utf-8"))
            assert stored["access_token"] == expected

    assert [(owner, name, cfg["url"], cfg["auth"], cfg["strict_redirect_headers"])
            for owner, name, cfg in probe] == [(home, "remote", f"https://{home.name}.example/mcp", "oauth", True)
                                               for home in sequence]
    assert "Authenticated" in capsys.readouterr().out
    assert all(path.read_bytes() == contents for path, contents in before.items())


@pytest.mark.parametrize("case", ["absent", "disabled", "non-oauth", "native-non-oauth", "ownership"])
def test_named_auth_keeps_refusals_and_config_ownership(tmp_path, capsys, probe, case):
    home = tmp_path / "alpha"
    seed_plugin(home, auth=case != "non-oauth", enabled=case != "disabled",
                native={"remote": {"url": "https://native.example/mcp"}} if case == "native-non-oauth" else None)
    before = (home / "config.yaml").read_bytes()
    token = set_hermes_home_override(home)
    try:
        if case == "ownership":
            mcp_config.cmd_mcp_reauth(argparse.Namespace(name=None, all=True))
            mcp_config.cmd_mcp_remove(argparse.Namespace(name="remote"))
        else:
            mcp_config.cmd_mcp_login(argparse.Namespace(name="missing" if case == "absent" else "remote", flow=None))
    finally:
        reset_hermes_home_override(token)

    assert probe == []
    message = "not configured for OAuth" if "oauth" in case else "not found"
    assert message in capsys.readouterr().out
    assert not (home / "mcp-tokens").exists()
    assert (home / "config.yaml").read_bytes() == before
