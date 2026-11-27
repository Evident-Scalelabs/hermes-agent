"""Retained typed browser handlers preserve input and scrub display-facing echoes."""

import json

import pytest

from agent import display, redact
from tools import browser_tool
from tools.registry import registry


@pytest.mark.parametrize("success", [True, False])
@pytest.mark.parametrize("text", ["ordinary search words", "sk-" + "A" * 30])
def test_registered_browser_type_preserves_input_and_scrubs_echoes(monkeypatch, success, text):
    monkeypatch.setattr(redact, "_REDACT_ENABLED", False)
    assert redact.redact_sensitive_text(text) == text
    sent = []

    def local_command(_task_id, command, args):
        sent.append((command, args))
        return {"success": success, "error": f"Could not type {text}",
                "fallback_warning": {"echoes": [f"Attempted {text}"]}}

    monkeypatch.setattr(browser_tool._session, "_run_browser_command", local_command)

    raw = registry.dispatch("browser_type", {"ref": "@field", "text": text}, task_id="type-redaction")
    assert isinstance(raw, str)
    result = json.loads(raw)
    assert result["success"] is success
    assert sent == [("fill", ["@field", text])]
    if text.startswith("sk-"):
        assert text not in raw
    else:
        assert text in raw


def test_browser_type_echo_scrubbing_preserves_nested_values_and_original(monkeypatch):
    monkeypatch.setattr(redact, "_REDACT_ENABLED", False)
    secret = "sk-" + "B" * 30
    original = {"error": f"Attempted {secret}", "metadata": [({"text": secret}, 7, None)]}
    before = repr(original)
    result = display.redact_browser_typed_text_for_display(original, secret)

    assert secret not in repr(result)
    assert result["metadata"][0][1:] == (7, None)
    assert isinstance(result["metadata"][0], tuple)
    assert repr(original) == before
    assert display.redact_browser_typed_text_for_display(original, "ordinary words") is original
