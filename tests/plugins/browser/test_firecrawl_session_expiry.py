"""Firecrawl expiry must reach the existing cloud-session cleanup owner."""

from unittest.mock import Mock

import pytest


@pytest.fixture
def firecrawl(monkeypatch):
    from agent.browser_registry import get_provider
    from hermes_cli.plugins import _ensure_plugins_discovered

    _ensure_plugins_discovered()
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    provider = get_provider("firecrawl")
    response = Mock(ok=True)
    response.json.return_value = {
        "id": "remote-session",
        "cdpUrl": "wss://browser.example/cdp",
        "expiresAt": "2020-01-01T00:05:00Z",
    }
    post = Mock(return_value=response)
    monkeypatch.setattr("requests.post", post)
    return provider, response, post


@pytest.mark.parametrize("expiry", ["2020-01-01T00:05:00Z", None])
def test_firecrawl_preserves_optional_provider_expiry(firecrawl, expiry):
    provider, response, post = firecrawl
    if expiry is None:
        response.json.return_value.pop("expiresAt")

    session = provider.create_session("task")

    assert session.get("expires_at") == expiry
    assert session["bb_session_id"] == "remote-session"
    assert session["cdp_url"] == "wss://browser.example/cdp"
    assert post.call_count == 1


def test_expired_firecrawl_cleanup_releases_without_cdp_or_repurchase(firecrawl, monkeypatch):
    from tools import browser_tool, browser_tool_cloud, browser_tool_lifecycle, browser_tool_session

    provider, _, post = firecrawl
    session = provider.create_session("task")
    session["_cdp_target_id"] = "owned-tab"
    monkeypatch.setattr(browser_tool, "_active_sessions", {"task": session})
    monkeypatch.setattr(browser_tool, "_session_last_activity", {"task": 1.0})
    monkeypatch.setattr(browser_tool, "_session_owner_homes", {})
    monkeypatch.setattr(browser_tool, "_last_active_session_key", {})
    monkeypatch.setattr(browser_tool, "_maybe_stop_recording", Mock())
    monkeypatch.setattr("tools.browser_tool_cdp._stop_cdp_supervisor", Mock())
    monkeypatch.setattr(browser_tool.os.path, "exists", lambda path: False)
    monkeypatch.setattr(browser_tool_cloud, "_get_cloud_provider", lambda: provider)
    close = Mock(return_value=True)
    monkeypatch.setattr(provider, "close_session", close)
    command = Mock(return_value={"success": False, "error": "401 Unauthorized"})
    monkeypatch.setattr(browser_tool_session, "_run_browser_command", command)
    create = Mock(side_effect=AssertionError("cleanup must not purchase a session"))
    monkeypatch.setattr(provider, "create_session", create)

    assert browser_tool_lifecycle.cleanup_browser("task") is True

    command.assert_not_called()
    create.assert_not_called()
    close.assert_called_once_with("remote-session")
    assert "task" not in browser_tool._active_sessions
    assert "task" not in browser_tool._session_last_activity
    assert post.call_count == 1
