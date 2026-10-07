"""Provider expiry reaches background supervision without another connection purchase."""

import asyncio
import threading

import pytest
import websockets

from tools import browser_supervisor, browser_tool, browser_tool_cdp, browser_tool_lifecycle


@pytest.mark.parametrize("drop_with_error", [False, True])
def test_provider_expiry_stops_supervisor_without_redial(monkeypatch, caplog, drop_with_error):
    clock = [100.0]
    monkeypatch.setattr(browser_tool_lifecycle.time, "time", lambda: clock[0])
    monkeypatch.setattr(browser_tool, "_active_sessions", {
        "expiring-task": {
            "cdp_url": "wss://browser.example/cdp",
            "_cdp_target_id": "owned-tab",
            "expires_at": "1970-01-01T00:03:20Z",
        },
    })
    monkeypatch.setattr(browser_tool_cdp, "_get_cdp_override", lambda: "")
    registry = browser_supervisor._SupervisorRegistry()
    monkeypatch.setattr(browser_supervisor, "SUPERVISOR_REGISTRY", registry)
    read_started = threading.Event()
    drop_socket = threading.Event()
    dials = []
    real_sleep = asyncio.sleep

    class Socket:
        async def close(self):
            pass

    async def connect(*args, **kwargs):
        dials.append(args)
        if len(dials) > 1:
            raise ConnectionError("401 Unauthorized")
        return Socket()

    async def attach(self):
        pass

    async def read(self):
        read_started.set()
        while not drop_socket.is_set():
            await real_sleep(0.001)
        if drop_with_error:
            raise ConnectionError("provider ended the browser session")

    async def fast_sleep(delay):
        await real_sleep(0)

    monkeypatch.setattr(websockets, "connect", connect)
    monkeypatch.setattr(browser_supervisor.CDPSupervisor, "_attach_initial_page", attach)
    monkeypatch.setattr(browser_supervisor.CDPSupervisor, "_read_loop", read)
    monkeypatch.setattr(browser_supervisor.asyncio, "sleep", fast_sleep)

    with caplog.at_level("WARNING", logger="tools.browser_supervisor"):
        browser_tool_cdp._ensure_cdp_supervisor("expiring-task")
        supervisor = registry.get("expiring-task")
        assert supervisor is not None
        try:
            assert read_started.wait(2.0)
            clock[0] = 200.0
            drop_socket.set()
            supervisor._thread.join(timeout=3.0)

            assert not supervisor._thread.is_alive()
            assert supervisor.snapshot().active is False
            assert registry.get("expiring-task") is None
            assert len(dials) == 1
            assert not caplog.records
        finally:
            drop_socket.set()
            supervisor.stop()
            registry.stop("expiring-task")
