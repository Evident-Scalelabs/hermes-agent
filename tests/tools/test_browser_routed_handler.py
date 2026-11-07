"""The registry handler for typed browser_* tools must reach the tool function."""

from tools import browser_tool
from tools.registry import registry


def test_registered_browser_tool_reaches_its_function(monkeypatch):
    calls = []
    monkeypatch.setattr(
        browser_tool, "browser_navigate",
        lambda url, task_id=None: calls.append((url, task_id)) or '{"success": true}',
    )
    result = registry.get_entry("browser_navigate").handler(
        {"url": "https://example.com/"}, task_id="t1",
    )
    assert result == '{"success": true}'
    assert calls == [("https://example.com/", "t1")]
