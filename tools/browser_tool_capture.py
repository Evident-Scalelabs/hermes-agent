"""Bounded optional screenshots for native in-process observers.

The CLI's screenshot CDP wait is 30s, equal to a plugin callback's default
deadline. Use the native captured connection so a missing image cannot strand
the callback or poison the browser session used by subsequent model tools.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any


def _existing_capture_target(existing: dict[str, Any]) -> tuple[str, str, tuple[Any, ...]]:
    """Read the native daemon's exact binding and Chrome endpoint without a CLI command."""
    import psutil
    from tools import browser_tool_lifecycle as lifecycle, browser_tool_session as sessions
    from tools.browser_tool_origin import origin as bt

    name = existing['session_name']
    socket_dir = str(Path(bt._socket_safe_tmpdir()) / f'agent-browser-{name}')
    binding = json.loads((Path(socket_dir) / f'{name}.target').read_text(encoding='utf-8-sig'))
    target = existing.get('_cdp_target_id') or binding['targetId']
    if not target or binding['targetId'] != target:
        raise RuntimeError('Native task target binding unavailable or changed')
    endpoint = existing.get('cdp_url')
    if endpoint:
        return endpoint, target, (endpoint, target)
    pid = sessions._read_browser_daemon_pid(socket_dir, name)
    if pid is None or not lifecycle._verify_reapable_browser_daemon(pid, socket_dir, name):
        raise RuntimeError('Native browser daemon ownership unavailable')
    daemon = psutil.Process(pid)
    profiles = {arg.split('=', 1)[1] for child in daemon.children(recursive=True)
                for arg in child.cmdline() if arg.startswith('--user-data-dir=')}
    if len(profiles) != 1:
        raise RuntimeError('Native Chrome profile identity unavailable')
    port, browser_path = (Path(profiles.pop()) / 'DevToolsActivePort').read_text(encoding='utf-8-sig').splitlines()[:2]
    if not port.isdigit() or not browser_path.startswith('/devtools/browser/') or not daemon.is_running():
        raise RuntimeError('Native Chrome endpoint unavailable')
    endpoint = f'ws://127.0.0.1:{port}{browser_path}'
    return endpoint, target, (endpoint, target, pid, daemon.create_time())


def capture_browser_screenshot(task_id: str, path: Path, *, timeout: float = 10.0) -> dict[str, Any]:
    """Capture the existing task's active viewport within one total time budget.

    Never creates, recycles or switches a browser. A CDP timeout cancels the native
    response future; Chrome has no screenshot-cancellation command. Late replies
    are ignored and cannot write the capture file or hold the CLI daemon's lock.
    """
    from tools import browser_tool_session as sessions
    from tools.browser_supervisor import SUPERVISOR_REGISTRY
    from tools.browser_tool_origin import origin as bt
    from psutil import Error as ProcessError

    deadline = time.monotonic() + timeout
    key = bt._last_session_key(task_id)
    with bt._cleanup_lock:
        existing = bt._active_sessions.get(key)
    if existing is None or not bt._session_info_owned_by_task(existing, task_id, key):
        return {"success": False, "error": "No existing native browser session"}

    def remaining() -> float:
        # CapturedCDP.call has a one-second scheduling grace after its CDP wait.
        budget = deadline - time.monotonic() - 1.0
        if budget <= 0:
            raise TimeoutError("Native screenshot capture budget exhausted")
        return budget

    supervisor = None
    try:
        endpoint, target, identity = _existing_capture_target(existing)
        remaining()
        previous = SUPERVISOR_REGISTRY.get(key, include_capture_only=True)
        if previous and not previous.capture_only and (previous.cdp_url != endpoint or previous.target_id != target):
            return {"success": False, "error": "Native observer belongs to a different browser target"}
        with bt._cleanup_lock:
            if bt._active_sessions.get(key) is not existing:
                return {"success": False, "error": "Native browser session changed during capture"}
        supervisor = SUPERVISOR_REGISTRY.get_or_start(key, endpoint, target_id=target,
            capture_only=True, start_timeout=remaining())
        with bt._cleanup_lock:
            if bt._active_sessions.get(key) is not existing:
                return {"success": False, "error": "Native browser session changed during attachment"}
        channel = SUPERVISOR_REGISTRY.capture(key, timeout=remaining())
        if SUPERVISOR_REGISTRY.get(key, include_capture_only=True) is not supervisor:
            return {"success": False, "error": "Native capture connection replaced during attachment"}
        def screenshot() -> dict[str, Any]:
            reply = channel.call("Page.captureScreenshot", {"format": "png", "fromSurface": True},
                session_id=channel.page_session_id, timeout=remaining())
            return {"success": True, "image": reply["result"]["data"]}
        result = sessions.run_fenced(existing, screenshot)
        if not result.get("success"):
            return result
        remaining()
        with bt._cleanup_lock:
            if (bt._active_sessions.get(key) is not existing or not channel.is_valid()
                    or not bt._session_info_owned_by_task(existing, task_id, key)
                    or _existing_capture_target(existing)[2] != identity):
                return {"success": False, "error": "Native browser session changed during capture"}
            remaining()
            path.write_bytes(base64.b64decode(result["image"], validate=True))
        return {"success": True, "data": {"path": str(path)}}
    except TimeoutError:
        return {"success": False, "error": "Native screenshot capture timed out", "code": "capture_timeout"}
    except (RuntimeError, OSError, ValueError, KeyError, ProcessError) as exc:
        return {"success": False, "error": str(exc)}
    finally:
        if supervisor is not None and supervisor.capture_only:
            with bt._cleanup_lock:
                current = bt._active_sessions.get(key)
            if current is not existing:
                with SUPERVISOR_REGISTRY._lock:
                    if SUPERVISOR_REGISTRY._by_task.get(key) is supervisor:
                        SUPERVISOR_REGISTRY._by_task.pop(key)
                supervisor.stop(timeout=0)
