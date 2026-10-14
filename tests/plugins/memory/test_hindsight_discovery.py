"""The retained Evident provider still resolves through v0.22's native loader."""
from pathlib import Path

import pytest


def test_native_discovery_loads_managed_reader_without_retention(tmp_path, monkeypatch):
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from plugins.memory import load_memory_provider
    from plugins.memory.hindsight import HindsightMemoryProvider

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("pm.ensure_import", lambda *_args, **_kwargs: None)
    token = set_secret_scope({
        "HINDSIGHT_MODE": "local_external",
        "HINDSIGHT_API_URL": "https://memory.example.test",
        "HINDSIGHT_BANK_ID": "site-workspace-example",
        "HINDSIGHT_AUTO_RETAIN": "false",
        "HINDSIGHT_RETAIN_TOOL": "false",
        "HINDSIGHT_RECALL_TAGS": "scope:site",
        "HINDSIGHT_RECALL_TAGS_MATCH": "all_strict",
    })
    try:
        provider = load_memory_provider("hindsight", register_skills=False)
        assert isinstance(provider, HindsightMemoryProvider)
        provider.initialize("native-discovery-fixture", hermes_home=str(tmp_path))
        assert provider._bank_id == "site-workspace-example"
        assert provider._auto_retain is False
        assert provider._recall_tags == ["scope:site"]
        assert provider._recall_tags_match == "all_strict"
        assert "hindsight_retain" not in {tool["name"] for tool in provider.get_tool_schemas()}
        provider.sync_turn("client message", "canonical result")
        assert provider._retain_queue.empty()
    finally:
        reset_secret_scope(token)


def test_update_migration_keeps_the_present_bundled_provider(tmp_path, monkeypatch):
    from hermes_cli.memory_provider_migration import migrate_home

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config = "memory:\n  provider: hindsight\n  memory_enabled: false\n"
    (tmp_path / "config.yaml").write_text(config, encoding="utf-8")
    assert migrate_home(
        tmp_path,
        install=lambda _name: pytest.fail("Bundled Hindsight must not be replaced by a catalog install"),
        say=lambda _message: pytest.fail("A present provider needs no migration"),
    ) is None
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == config
