"""Behavior contract for ``SUPERVISOR_REGISTRY.capture`` (public CDP seam for trusted plugins).

A real ``CDPSupervisor`` talks to a real local WebSocket server that speaks just enough CDP
(getTargets / attachToTarget / echo). Each connection gets its own page session id
(``S1``, ``S2``, ...) so the tests can tell which socket a frame travelled on.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time

import pytest

from tools.browser_supervisor import _SupervisorRegistry
from tools.browser_supervisor_capture import CapturedCDPInvalid


class _FakeCDP:
    def __init__(self) -> None:
        self.frames: list[tuple[int, str, str | None]] = []  # (connection no, method, sessionId)
        self.connections: list = []
        self.url = ""
        self.hang_capture = False
        self.hang_attach = False
        self.late_captures = []
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()
        threading.Thread(target=self._serve, args=(ready,), daemon=True).start()
        assert ready.wait(5)

    def _serve(self, ready: threading.Event) -> None:
        from websockets.asyncio.server import serve

        async def main():
            async with serve(self._handle, "127.0.0.1", 0) as server:
                self.url = f"ws://127.0.0.1:{list(server.sockets)[0].getsockname()[1]}/devtools/browser/x"
                ready.set()
                await asyncio.Event().wait()

        self.loop.run_until_complete(main())

    async def _handle(self, ws) -> None:
        self.connections.append(ws)
        conn = len(self.connections)
        async for raw in ws:
            msg = json.loads(raw)
            method, sid = msg["method"], msg.get("sessionId")
            self.frames.append((conn, method, sid))
            if method == "Test.hang":
                continue
            if method == "Target.attachToTarget" and self.hang_attach:
                continue
            if method == "Page.captureScreenshot" and self.hang_capture:
                self.late_captures.append((ws, msg))
                continue
            if method == "Test.error":
                await ws.send(json.dumps({"id": msg["id"], "error": {"code": -32000, "message": "boom"}}))
                continue
            result = {"echo": method, "sessionId": sid, "params": msg.get("params")}
            if method == "Target.getTargets":
                result = {"targetInfos": [{"targetId": target, "type": "page", "url": "about:blank"}
                                          for target in ("T1", "T2")]}
            elif method == "Target.attachToTarget":
                result = {"sessionId": f"S{conn}"}
            elif method == "Page.captureScreenshot":
                result = {"data": base64.b64encode(b"native-image").decode()}
            await ws.send(json.dumps({"id": msg["id"], "result": result}))

    def drop_current(self) -> None:
        asyncio.run_coroutine_threadsafe(self.connections[-1].close(), self.loop).result(5)

    def methods_on(self, conn: int) -> list[str]:
        return [m for c, m, _ in self.frames if c == conn]


@pytest.fixture
def cdp():
    return _FakeCDP()


@pytest.fixture
def registry():
    reg = _SupervisorRegistry()
    yield reg
    reg.stop_all()


def _wait(pred, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def test_call_round_trips_on_captured_connection(cdp, registry):
    registry.get_or_start("t", cdp.url, start_timeout=5)
    handle = registry.capture("t")
    assert handle.is_valid() and handle.page_session_id == "S1"

    reply = handle.call("Runtime.evaluate", {"expression": "1"}, session_id=handle.page_session_id)
    assert reply["result"] == {"echo": "Runtime.evaluate", "sessionId": "S1", "params": {"expression": "1"}}
    assert handle.call("Target.getTargets")["result"]["targetInfos"][0]["targetId"] == "T1"  # browser-level

    with pytest.raises(RuntimeError, match="boom"):
        handle.call("Test.error")
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        handle.call("Test.hang", timeout=0.3)
    assert time.monotonic() - started < 2
    assert handle.is_valid()  # neither an error reply nor a timeout invalidates the handle

    with pytest.raises(CapturedCDPInvalid):
        registry.capture("no-such-task")


def test_handle_never_follows_a_reconnect_or_replacement(cdp, registry):
    sup = registry.get_or_start("t", cdp.url, start_timeout=5)
    old = registry.capture("t")

    # A call in flight when the socket drops fails promptly as invalidation, not at its timeout.
    errors: list = []
    caller = threading.Thread(target=lambda: errors.append(_raises(lambda: old.call("Test.hang", timeout=30))))
    caller.start()
    _wait(lambda: "Test.hang" in cdp.methods_on(1))
    started = time.monotonic()
    cdp.drop_current()
    caller.join(10)
    assert errors and isinstance(errors[0], CapturedCDPInvalid), errors
    assert time.monotonic() - started < 5

    _wait(lambda: len(cdp.connections) == 2 and sup.snapshot().active)
    assert not old.is_valid()
    with pytest.raises(CapturedCDPInvalid):
        old.call("Probe.afterReconnect", session_id=old.page_session_id)
    assert "Probe.afterReconnect" not in cdp.methods_on(2)  # never silently retargeted

    fresh = registry.capture("t")
    assert fresh.page_session_id == "S2"
    assert fresh.call("Probe.fresh", session_id=fresh.page_session_id)["result"]["sessionId"] == "S2"

    registry.stop("t")  # stop / replacement in the registry invalidates too
    assert not fresh.is_valid()
    with pytest.raises(CapturedCDPInvalid):
        fresh.call("Probe.afterStop")


def _raises(fn) -> BaseException | None:
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 — handed back to the asserting thread
        return exc
    return None


def _native_capture_session(monkeypatch, cdp, registry):
    from tools import browser_supervisor, browser_tool, browser_tool_capture

    session = {"session_name": "owned-native", "features": {"local": True}}
    active = {"target": "T1"}
    monkeypatch.setattr(browser_tool, "_active_sessions", {"fixture-local": session})
    monkeypatch.setattr(browser_tool, "_last_session_key", lambda task: task + "-local")
    monkeypatch.setattr(browser_supervisor, "SUPERVISOR_REGISTRY", registry)
    def identity(existing):
        if not active['target'] or (existing.get('_cdp_target_id') and existing['_cdp_target_id'] != active['target']):
            raise RuntimeError('Task target unavailable')
        return cdp.url, active['target'], (cdp.url, active['target'])
    monkeypatch.setattr(browser_tool_capture, '_existing_capture_target', identity)
    return session, active


def test_optional_screenshot_timeout_keeps_exact_session_and_ignores_late_image(tmp_path, monkeypatch, cdp, registry):
    from tools import browser_tool
    from tools.browser_tool_capture import capture_browser_screenshot

    session, _ = _native_capture_session(monkeypatch, cdp, registry)
    cdp.hang_capture = True
    path = tmp_path / "late.png"
    started = time.monotonic()
    result = capture_browser_screenshot("fixture", path, timeout=3)
    assert result["code"] == "capture_timeout" and time.monotonic() - started < 4
    assert not path.exists() and browser_tool._active_sessions["fixture-local"] is session
    handle = registry.capture("fixture-local")
    assert handle.is_valid() and registry.get("fixture-local") is None
    assert not any(method in cdp.methods_on(1) for method in (
        "Target.createTarget", "Page.enable", "Runtime.enable", "Target.setAutoAttach", "Fetch.enable"))
    ws, msg = cdp.late_captures[0]
    late = {"id": msg["id"], "result": {"data": base64.b64encode(b"late-image").decode()}}
    asyncio.run_coroutine_threadsafe(ws.send(json.dumps(late)), cdp.loop).result(5)
    assert handle.call("Runtime.evaluate", session_id=handle.page_session_id)["result"]["echo"] == "Runtime.evaluate"
    assert not path.exists()
    cdp.hang_capture = False
    assert capture_browser_screenshot("fixture", tmp_path / "next.png")["success"]
    assert (tmp_path / "next.png").read_bytes() == b"native-image"


def test_optional_screenshot_never_creates_browser_or_captures_missing_target(tmp_path, monkeypatch, cdp, registry):
    from tools import browser_tool
    from tools.browser_tool_capture import capture_browser_screenshot

    session, active = _native_capture_session(monkeypatch, cdp, registry)
    browser_tool._active_sessions.clear()
    assert not capture_browser_screenshot("fixture", tmp_path / "none.png")["success"]
    assert not cdp.connections
    browser_tool._active_sessions["fixture-local"] = session
    active["target"] = None
    assert not capture_browser_screenshot("fixture", tmp_path / "missing.png")["success"]
    assert not cdp.connections and not list(tmp_path.glob("*.png"))


def test_optional_screenshot_tracks_local_tab_but_refuses_foreign_pinned_target(tmp_path, monkeypatch, cdp, registry):
    from tools.browser_tool_capture import capture_browser_screenshot

    session, active = _native_capture_session(monkeypatch, cdp, registry)
    assert capture_browser_screenshot("fixture", tmp_path / "first.png")["success"]
    active["target"] = "T2"
    assert capture_browser_screenshot("fixture", tmp_path / "second.png")["success"]
    assert registry.get("fixture-local", include_capture_only=True).target_id == "T2"
    assert (2, "Page.captureScreenshot", "S2") in cdp.frames
    session["_cdp_target_id"] = "T1"
    assert not capture_browser_screenshot("fixture", tmp_path / "foreign.png")["success"]
    assert not (tmp_path / "foreign.png").exists()


def test_optional_screenshot_refuses_session_replacement_before_file_write(tmp_path, monkeypatch, cdp, registry):
    from tools import browser_tool
    from tools.browser_tool_capture import capture_browser_screenshot

    _native_capture_session(monkeypatch, cdp, registry)
    cdp.hang_capture = True
    results = []
    path = tmp_path / "old.png"
    worker = threading.Thread(target=lambda: results.append(capture_browser_screenshot("fixture", path)))
    worker.start()
    _wait(lambda: bool(cdp.late_captures))
    browser_tool._active_sessions["fixture-local"] = {"session_name": "replacement"}
    ws, msg = cdp.late_captures[0]
    reply = {"id": msg["id"], "result": {"data": base64.b64encode(b"old-image").decode()}}
    asyncio.run_coroutine_threadsafe(ws.send(json.dumps(reply)), cdp.loop).result(5)
    worker.join(5)
    assert not worker.is_alive() and not results[0]["success"] and not path.exists()


def test_capture_attachment_timeout_cancels_unregistered_transport_worker(monkeypatch, cdp, registry):
    from tools import browser_supervisor

    created = []
    original = browser_supervisor.CDPSupervisor
    class RecordedSupervisor(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)
    monkeypatch.setattr(browser_supervisor, "CDPSupervisor", RecordedSupervisor)
    cdp.hang_attach = True
    with pytest.raises(TimeoutError):
        registry.get_or_start("fixture", cdp.url, target_id="T1", start_timeout=0.2, capture_only=True)
    assert registry.get("fixture") is None
    created[0]._thread.join(5)
    assert not created[0]._thread.is_alive()
    assert not any(method in cdp.methods_on(1) for method in ("Target.createTarget", "Fetch.enable"))


def test_cleanup_during_capture_attachment_releases_only_that_transport(tmp_path, monkeypatch, cdp, registry):
    from tools import browser_tool
    from tools.browser_tool_capture import capture_browser_screenshot

    _native_capture_session(monkeypatch, cdp, registry)
    start = registry.get_or_start
    created = []
    def cleanup_during_attach(*args, **kwargs):
        transport = start(*args, **kwargs)
        created.append(transport)
        browser_tool._active_sessions.clear()
        return transport
    monkeypatch.setattr(registry, 'get_or_start', cleanup_during_attach)
    assert not capture_browser_screenshot('fixture', tmp_path / 'cleaned.png')['success']
    assert registry.get('fixture-local', include_capture_only=True) is None
    created[0]._thread.join(5)
    assert not created[0]._thread.is_alive() and not (tmp_path / 'cleaned.png').exists()


def test_capture_never_follows_an_observer_replacement_between_attach_and_pin(tmp_path, monkeypatch, cdp, registry):
    from tools.browser_tool_capture import capture_browser_screenshot

    _native_capture_session(monkeypatch, cdp, registry)
    capture = registry.capture
    replacement = []
    def replace_then_pin(key, **kwargs):
        replacement.append(registry.get_or_start(key, cdp.url, target_id='T2'))
        return capture(key, **kwargs)
    monkeypatch.setattr(registry, 'capture', replace_then_pin)
    assert not capture_browser_screenshot('fixture', tmp_path / 'wrong.png')['success']
    assert registry.get('fixture-local') is replacement[0]
    assert not any(method == 'Page.captureScreenshot' for _, method, _ in cdp.frames)
    assert not (tmp_path / 'wrong.png').exists()
