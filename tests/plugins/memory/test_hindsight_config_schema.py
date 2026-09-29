"""Tests for Hindsight's declared config surface."""

from plugins.memory.config_schema import (
    KIND_SECRET,
    KIND_SELECT,
    get_provider_config_schema,
)


def test_hindsight_is_declared():
    provider = get_provider_config_schema("hindsight")

    assert provider is not None
    assert provider.label == "Hindsight"
    assert {field.key for field in provider.fields} == {
        "mode",
        "api_key",
        "api_url",
        "bank_id",
        "recall_budget",
    }


def test_fields_are_all_inline():
    provider = get_provider_config_schema("hindsight")
    assert provider is not None

    # Hindsight is simple enough to render fully in the compact panel, so it
    # never grows a Full config… modal.
    assert all(field.inline for field in provider.fields)


def test_mode_gating_is_expressed_as_select_options():
    provider = get_provider_config_schema("hindsight")
    assert provider is not None

    mode = next(field for field in provider.fields if field.key == "mode")
    assert mode.kind == KIND_SELECT
    assert mode.allowed_values() == {"cloud", "local_external"}
    # local_embedded is intentionally unsupported on desktop.
    assert "local_embedded" not in mode.allowed_values()


def test_api_key_is_a_secret_bound_to_env():
    provider = get_provider_config_schema("hindsight")
    assert provider is not None

    api_key = next(field for field in provider.fields if field.key == "api_key")
    assert api_key.kind == KIND_SECRET
    assert api_key.is_secret is True
    assert api_key.env_key == "HINDSIGHT_API_KEY"


def test_connection_fields_show_environment_without_writing_config(tmp_path, monkeypatch):
    from hermes_cli.web_server_memory import _field_value, _normalize_memory_provider_schema
    from hermes_cli.web_routers.memory_providers import _declared_provider_payload
    from plugins.memory.hindsight import HindsightMemoryProvider

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    values = {"mode": "local_external", "api_url": "https://memory.example.test", "bank_id": "profile-example"}
    for key, value in values.items():
        monkeypatch.setenv("HINDSIGHT_" + key.upper(), value)
    (tmp_path / ".env").write_text("\n".join("HINDSIGHT_" + key.upper() + "=" + value for key, value in values.items()))
    fields = _normalize_memory_provider_schema("hindsight", HindsightMemoryProvider())
    for field in fields:
        if field["key"] in values:
            assert _field_value(field, {}) == values[field["key"]]
    declared = _declared_provider_payload(get_provider_config_schema("hindsight"))
    shown = {field["key"]: field["value"] for field in declared["fields"]}
    assert {key: shown[key] for key in values} == values
    assert not (tmp_path / "hindsight" / "config.json").exists()
