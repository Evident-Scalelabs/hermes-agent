"""Optional screenshots bind existing native files/processes without launching a browser."""

import base64
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def native_session(tmp_path, monkeypatch):
    import psutil
    from tools import browser_tool, browser_tool_lifecycle, browser_tool_session

    socket_dir = tmp_path / "agent-browser-owned"
    profile = tmp_path / "chrome-profile"
    socket_dir.mkdir()
    profile.mkdir()
    binding = socket_dir / "owned.target"
    binding.write_text(json.dumps({"targetId": "T1", "pinned": False}))
    (profile / "DevToolsActivePort").write_text("9222\n/devtools/browser/exact-browser\n")
    session = {"session_name": "owned", "session_key": "fixture", "owner_task_id": "fixture"}
    state = {"pid": 4321, "owned": True, "running": True, "created": 100.0, "forbidden_calls": []}
    daemon = SimpleNamespace(
        children=lambda **_: [SimpleNamespace(cmdline=lambda: ["chrome", f"--user-data-dir={profile}"])],
        is_running=lambda: state["running"], create_time=lambda: state["created"],
    )
    monkeypatch.setattr(psutil, "Process", lambda pid: daemon)
    monkeypatch.setattr(browser_tool, "_socket_safe_tmpdir", lambda: str(tmp_path))
    monkeypatch.setattr(browser_tool_session, "_read_browser_daemon_pid", lambda *_: state["pid"])
    monkeypatch.setattr(browser_tool_lifecycle, "_verify_reapable_browser_daemon", lambda *_: state["owned"])
    monkeypatch.setattr(browser_tool, "_active_sessions", {"fixture": session})
    monkeypatch.setattr(browser_tool, "_last_session_key", lambda task: task)
    monkeypatch.setattr(browser_tool_session, "run_fenced", lambda existing, fn: fn())
    def forbidden(*args, **kwargs):
        state["forbidden_calls"].append((args, kwargs))
        raise AssertionError("Optional capture must not invoke CLI dispatch or browser lifecycle recovery")
    monkeypatch.setattr(browser_tool_session, "_dispatch_browser_command", forbidden)
    monkeypatch.setattr(browser_tool_session, "_prepare_session_socket_dir", forbidden)
    monkeypatch.setattr(browser_tool_session, "_get_session_info", forbidden)
    monkeypatch.setattr(browser_tool_session, "_handle_browser_command_timeout", forbidden)
    return session, state, binding


def test_existing_local_and_cloud_identity_uses_native_binding_without_cli(native_session):
    from tools.browser_tool_capture import _existing_capture_target

    session, state, _ = native_session
    endpoint = "ws://127.0.0.1:9222/devtools/browser/exact-browser"
    assert _existing_capture_target(session) == (endpoint, "T1", (endpoint, "T1", 4321, 100.0))
    session.update(cdp_url="wss://cloud.example/existing", _cdp_target_id="T1")
    assert _existing_capture_target(session) == (session["cdp_url"], "T1", (session["cdp_url"], "T1"))
    session["_cdp_target_id"] = "foreign-target"
    with pytest.raises(RuntimeError, match="binding unavailable or changed"):
        _existing_capture_target(session)
    assert not state["forbidden_calls"]


@pytest.mark.parametrize("failure", ["missing_daemon", "stale_daemon", "exited_daemon", "missing_binding"])
def test_unavailable_native_identity_cannot_attach_or_launch(native_session, monkeypatch, tmp_path, failure):
    from tools import browser_supervisor, browser_tool
    from tools.browser_tool_capture import capture_browser_screenshot

    session, state, binding = native_session
    if failure == "missing_daemon":
        state["pid"] = None
    elif failure == "stale_daemon":
        state["owned"] = False
    elif failure == "exited_daemon":
        state["running"] = False
    else:
        binding.unlink()
    attached = []
    class NoAttachment:
        def get(self, *_args, **_kwargs):
            attached.append(True)
            raise AssertionError("Unavailable identity must be refused before CDP attachment")
    monkeypatch.setattr(browser_supervisor, "SUPERVISOR_REGISTRY", NoAttachment())
    path = tmp_path / "missing.png"
    assert not capture_browser_screenshot("fixture", path)["success"]
    assert not path.exists() and browser_tool._active_sessions["fixture"] is session
    assert not attached and not state["forbidden_calls"]


@pytest.mark.parametrize("change", ["binding", "daemon_generation", "endpoint"])
def test_native_identity_change_during_capture_discards_image(native_session, monkeypatch, tmp_path, change):
    from tools import browser_supervisor, browser_tool
    from tools.browser_tool_capture import capture_browser_screenshot

    session, state, binding = native_session
    class Channel:
        page_session_id = "exact-attached-page"
        def is_valid(self):
            return True
        def call(self, method, params, *, session_id, timeout):
            assert method == "Page.captureScreenshot" and session_id == self.page_session_id and timeout > 0
            if change == "binding":
                binding.write_text(json.dumps({"targetId": "T2", "pinned": False}))
            elif change == "daemon_generation":
                state["created"] += 1
            else:
                (tmp_path / "chrome-profile" / "DevToolsActivePort").write_text("9222\n/devtools/browser/replacement\n")
            return {"result": {"data": base64.b64encode(b"old-image").decode()}}
    supervisor = SimpleNamespace(capture_only=True)
    def attach(key, endpoint, *, target_id, capture_only, start_timeout):
        assert key == "fixture" and target_id == "T1" and capture_only and start_timeout > 0
        assert endpoint == "ws://127.0.0.1:9222/devtools/browser/exact-browser"
        return supervisor
    registry = SimpleNamespace(get=lambda *_a, **_k: None, get_or_start=attach,
                               capture=lambda *_a, **_k: Channel())
    monkeypatch.setattr(browser_supervisor, "SUPERVISOR_REGISTRY", registry)
    path = tmp_path / "changed.png"
    assert not capture_browser_screenshot("fixture", path)["success"]
    assert not path.exists() and browser_tool._active_sessions["fixture"] is session
    assert not state["forbidden_calls"]


def test_bounded_hook_reports_absolute_dispatch_deadline_before_worker_start(monkeypatch):
    from hermes_cli import plugins_dispatch
    from hermes_cli.plugins import PluginManager

    clock = {"now": 100.0}
    original_thread = plugins_dispatch.threading.Thread
    class DelayedWorker(original_thread):
        def start(self):
            clock["now"] = 110.0
            return super().start()
    monkeypatch.setattr(plugins_dispatch.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(plugins_dispatch.threading, "Thread", DelayedWorker)
    payload = {"tool_name": "browser_snapshot", "tool_call_id": "call"}
    def observer(tool_name, hook_deadline):
        return tool_name, hook_deadline, hook_deadline - clock["now"]
    result = PluginManager()._run_hook_callback_bounded("post_tool_call", observer, payload, 30.0)
    assert result == ("browser_snapshot", 130.0, 20.0)
    assert payload == {"tool_name": "browser_snapshot", "tool_call_id": "call"}


def test_optional_capture_admission_preserves_incompatible_full_observer(monkeypatch):
    from tools import browser_supervisor

    registry = browser_supervisor._SupervisorRegistry()
    stopped = []
    observer = SimpleNamespace(cdp_url="wss://existing", target_id="owned", capture_only=False,
        _thread=SimpleNamespace(is_alive=lambda: True), _loop=SimpleNamespace(is_running=lambda: True),
        stop=lambda **kwargs: stopped.append(kwargs))
    registry._by_task["fixture"] = observer
    created = []
    def unexpected_supervisor(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(start=lambda **_: None)
    monkeypatch.setattr(browser_supervisor, "CDPSupervisor", unexpected_supervisor)
    with pytest.raises(RuntimeError):
        registry.get_or_start("fixture", "wss://different", target_id="other", capture_only=True)
    assert registry.get("fixture") is observer and not stopped and not created


def test_full_observer_upgrade_stops_capture_only_concurrent_winner(monkeypatch):
    from tools import browser_supervisor

    registry = browser_supervisor._SupervisorRegistry()
    stopped = []
    capture = SimpleNamespace(cdp_url="wss://existing", target_id="owned", capture_only=True,
                              stop=lambda **kwargs: stopped.append(kwargs))
    class FullObserver:
        def __init__(self, **kwargs):
            self.cdp_url, self.target_id, self.capture_only = kwargs["cdp_url"], kwargs["target_id"], False
        def start(self, **kwargs):
            registry._by_task["fixture"] = capture
    monkeypatch.setattr(browser_supervisor, "CDPSupervisor", FullObserver)
    full = registry.get_or_start("fixture", "wss://existing", target_id="owned")
    assert registry.get("fixture") is full and not full.capture_only
    assert stopped == [{"timeout": 0}]
