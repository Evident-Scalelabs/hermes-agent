"""Keep agent-browser dispatch uncertainty through native retries and model tools."""

import json

import pytest

from tools import browser_tool as browser
from tools import browser_tool_session as sessions
from tools.registry import registry


UNKNOWN = {
    "success": False,
    "error": "The command reached the daemon but no response came back; it was not retried",
    "code": "outcome_unknown",
}


@pytest.mark.parametrize("engine", ["chrome", "lightpanda"])
def test_dispatched_command_with_unknown_outcome_never_retries_or_switches_engine(monkeypatch, engine):
    task = "uncertain-task"
    session = {"session_name": "owned-session", "features": {"local": True}}
    monkeypatch.setattr(sessions, "_browser_command_preflight", lambda: {"browser_cmd": "agent-browser"})
    monkeypatch.setattr(sessions, "_get_session_info", lambda owner: session)
    monkeypatch.setattr(sessions, "run_fenced_pair", lambda info, fn: fn())
    monkeypatch.setattr("tools.interrupt.is_interrupted", lambda: False)
    dispatches = []

    def dispatch(owner, info, binary, command, args, timeout, override):
        dispatches.append((owner, info, command, args))
        # The CLI exits nonzero on this JSON failure. The parsed code owns the verdict.
        result = sessions._interpret_browser_command_output(command, json.dumps(UNKNOWN), "", 1)
        return engine, result

    monkeypatch.setattr(sessions, "_dispatch_browser_command", dispatch)
    monkeypatch.setattr(sessions, "_recycle_local_session", lambda *args: pytest.fail("Dispatched action recycled"))
    monkeypatch.setattr("tools.browser_tool_lightpanda_fallback._run_chrome_fallback_command",
                        lambda *args: pytest.fail("Dispatched action replayed in Chrome"))

    assert sessions._run_browser_command(task, "click", ["@e1"]) == UNKNOWN
    assert dispatches == [(task, session, "click", ["@e1"])]


@pytest.mark.parametrize(("name", "args"), [
    ("browser_navigate", {"url": "https://example.com"}),
    ("browser_click", {"ref": "@e1"}),
    ("browser_type", {"ref": "@e1", "text": "example"}),
    ("browser_console", {"expression": "document.title"}),
])
def test_native_tool_preserves_unknown_outcome_for_the_model(monkeypatch, name, args):
    monkeypatch.setattr(browser, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(browser, "_last_session_key", lambda task: task)
    monkeypatch.setattr(browser, "_navigation_session_key", lambda task, url: task)
    monkeypatch.setattr(browser, "_url_policy_error", lambda *args, **kw: None)
    monkeypatch.setattr(browser, "_blocked_private_page_action", lambda *args: None)
    monkeypatch.setattr(browser, "_eval_supervisor_fast_path", lambda *args: None)
    monkeypatch.setattr("tools.browser_tool_eval_policy._eval_ssrf_guard_active", lambda task: False)
    monkeypatch.setattr(sessions, "_get_session_info", lambda task: {"_first_nav": False})
    monkeypatch.setattr(sessions, "run_fenced", lambda info, fn: fn())
    monkeypatch.setattr(sessions, "_run_browser_command", lambda *args, **kw: dict(UNKNOWN))

    result = json.loads(registry.dispatch(name, args, task_id="uncertain-task"))

    assert result == UNKNOWN
