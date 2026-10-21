"""GW-23 (#134889): per-profile browser scope edges left after CLI-9.

A multiplexed gateway serves every profile from one process; a live ``/browser connect`` endpoint,
and a browser session belong to ONE profile.
"""
import threading

import pytest

from agent import secret_scope
from gateway.run import _profile_runtime_scope
from hermes_constants import get_hermes_home, hermes_home_key
from tools import browser_tool_cdp as bt_cdp
from tools import browser_harness_dirs as harness_dirs
from tools.browser_harness_dirs import claim_private_dir as _REAL_CLAIM  # conftest stubs it per test


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    monkeypatch.setattr(bt_cdp, "_live_overrides", {})
    return a, b


def _in_bare_thread(fn):
    """Run ``fn`` on a stdlib thread started WITHOUT the caller's copied context."""
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("v", fn()))
    t.start()
    t.join(5)
    return out["v"]


def test_a_bare_thread_on_a_multiplexed_gateway_never_resolves_the_launch_profiles_override(profiles, monkeypatch):
    """No profile scope bound on a multiplexed gateway: the launch profile's live endpoint is NOT the
    answer (``get_secret`` fails closed the same way). A bound scope still sees its own."""
    launch = get_hermes_home()
    with _profile_runtime_scope(launch, hydrate_secrets=False):
        bt_cdp.set_live_cdp_override("http://127.0.0.1:9401")
    monkeypatch.setattr(secret_scope, "_MULTIPLEX_ACTIVE", True)
    assert _in_bare_thread(bt_cdp.live_cdp_override) == ""
    assert _in_bare_thread(bt_cdp._get_cdp_override_raw) == ""
    with _profile_runtime_scope(launch, hydrate_secrets=False):
        assert bt_cdp.live_cdp_override() == "http://127.0.0.1:9401"


def test_single_profile_bare_thread_keeps_the_process_override(profiles):
    bt_cdp.set_live_cdp_override("http://127.0.0.1:9402")
    assert _in_bare_thread(bt_cdp.live_cdp_override) == "http://127.0.0.1:9402"
    assert hermes_home_key() in bt_cdp._live_overrides


# --- macOS AF_UNIX budget for a served profile's harness sockets -------------------------------------

_LONGEST_NAME = "n" * 64  # browser_harness/_ipc.py _NAME_RE: [A-Za-z0-9_-]{1,64}


def _sock_len(runtime_dir: str) -> int:
    """browser_harness/_ipc.py ``_sock_path``: ``<resolved BH_RUNTIME_DIR>/bu-<NAME>.sock`` when
    ``BH_RUNTIME_DIR_SHARED=1`` (pinned against the installed package by the test below)."""
    return len(f"{runtime_dir}/bu-{_LONGEST_NAME}.sock".encode())


@pytest.mark.parametrize(("platform", "budget"), [("darwin", 103 - 73), ("linux", 107 - 73), ("win32", None)])
def test_the_socket_dir_budget_is_sun_path_minus_a_64_char_session_socket(platform, budget):
    """macOS ``sun_path`` is 104 bytes (103 + NUL), Linux 108; Windows serves over loopback TCP."""
    assert harness_dirs.socket_dir_budget(platform) == budget


def test_a_default_macos_home_does_not_fit_and_the_short_temp_dir_does():
    """Pure length rule with macOS data (no host platform involved): under
    ``~/.config/browser-harness/runtime/p-<hash>`` a 9-letter account left room for ~31-character
    session names; ``/private/tmp/hbh-<12 hex>`` fits a 64-character one."""
    budget = harness_dirs.socket_dir_budget("darwin")
    home = "/Users/alexander/.config/browser-harness/runtime/p-0123456789ab"
    short = "/private/tmp/hbh-0123456789ab"  # no-tmp: ok — a macOS path as data, nothing is written
    assert not harness_dirs.fits_socket_budget(home, budget)
    assert harness_dirs.fits_socket_budget(short, budget) and _sock_len(short) <= 103
    assert harness_dirs.fits_socket_budget("x" * 500, None)  # no sun_path limit


def _kernel_accepts_sun_path(path: str) -> bool:
    """Ask the kernel ABI whether ``path`` fits ``sun_path``: an unbound dir gives ENOENT, an overlong
    path gives "AF_UNIX path too long" before any filesystem access."""
    import socket
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.bind(path)
    except OSError as e:
        return "too long" not in str(e)
    else:
        import os
        os.unlink(path)
        return True
    finally:
        s.close()


def test_the_short_socket_dir_is_claimed_only_when_private_and_ours(tmp_path):
    """The short dir sits in a world-writable root: a symlink or another user's/open dir is refused."""
    fresh = tmp_path / "hbh-fresh"
    assert _REAL_CLAIM(str(fresh)) and (fresh.stat().st_mode & 0o777) == 0o700
    assert _REAL_CLAIM(str(fresh))  # ours, 0700: reused
    open_dir = tmp_path / "hbh-open"
    open_dir.mkdir(mode=0o755)
    open_dir.chmod(0o755)
    assert not _REAL_CLAIM(str(open_dir))
    link = tmp_path / "hbh-link"
    link.symlink_to(fresh)
    assert not _REAL_CLAIM(str(link))


# --- per-profile harness tmp dir (screenshots, debug overlays, daemon logs) ---------------------------


# --- reap/publish race within one profile -----------------------------------------------------------


def test_a_session_that_resolved_the_old_endpoint_during_a_connect_is_closed_not_kept(profiles, monkeypatch):
    """``/browser connect`` reaps, publishes the new endpoint, then reaps again. A tool call that
    resolved the OLD endpoint before the publish but inserted its session after the second reap kept
    driving the old browser. The real ``_browser_connect`` handler runs mid-creation here."""
    from tools import browser_tool, browser_tool_lifecycle as lifecycle, browser_tool_session as bt_session
    from tui_gateway import server  # binds methods_browser helpers onto server globals

    a, _b = profiles
    sessions = {}
    monkeypatch.setattr(browser_tool, "_active_sessions", sessions)
    monkeypatch.setattr(lifecycle, "_start_browser_cleanup_thread", lambda: None)
    monkeypatch.setattr(bt_cdp, "_ensure_cdp_supervisor", lambda key: None)
    monkeypatch.setattr(server, "_cdp_http_reachable", lambda parsed, timeout=2.0: True)
    closed = []  # released by object: the stale session is never in ``sessions``
    monkeypatch.setattr(lifecycle, "_release_session_backend", lambda task_id, info: closed.append(info["cdp_url"]))
    monkeypatch.setattr(bt_session, "_browser_command_preflight", lambda: {"error": "no CLI in this test"})
    created = []

    def create(task_id, local):
        url = bt_cdp._get_cdp_override_raw()  # resolved before the connect publishes
        if not created:
            assert server._browser_connect("r1", {"url": "http://127.0.0.1:9502"})["result"]["connected"]
        created.append(url)
        return {"session_name": f"s{len(created)}", "cdp_url": url}
    monkeypatch.setattr(bt_session, "_create_session_for_key", create)

    with _profile_runtime_scope(a, hydrate_secrets=False):
        bt_cdp.set_live_cdp_override("http://127.0.0.1:9501")
        info = bt_session._get_session_info("task-a")
    assert info["cdp_url"] == "http://127.0.0.1:9502"
    assert sessions["task-a"] is info
    assert closed == ["http://127.0.0.1:9501"]


def test_a_stale_session_is_closed_without_ever_being_handed_to_a_concurrent_caller(profiles, monkeypatch):
    """A session found stale after creation is closed by object, never published first: while its
    backend ``close`` runs, a concurrent ``_get_session_info`` for the same key must not find it in
    ``_active_sessions`` (it would return a browser that is being closed underneath it)."""
    from tools import browser_tool, browser_tool_lifecycle as lifecycle, browser_tool_session as bt_session
    from tui_gateway import server

    a, _b = profiles
    sessions = {}
    monkeypatch.setattr(browser_tool, "_active_sessions", sessions)
    monkeypatch.setattr(lifecycle, "_start_browser_cleanup_thread", lambda: None)
    monkeypatch.setattr(bt_cdp, "_ensure_cdp_supervisor", lambda key: None)
    monkeypatch.setattr(bt_cdp, "_stop_cdp_supervisor", lambda key: None)
    monkeypatch.setattr(server, "_cdp_http_reachable", lambda parsed, timeout=2.0: True)
    monkeypatch.setattr(bt_session, "_browser_command_preflight", lambda: {"browser_cmd": "agent-browser"})
    visible_during_close = []

    def dispatch(task_id, info, browser_cmd, command, args, timeout, engine):
        if command == "close":  # what the existing-session path would hand a concurrent caller now
            visible_during_close.append((info["cdp_url"], (sessions.get(task_id) or {}).get("cdp_url")))
        return "chrome", {"success": True}
    monkeypatch.setattr(bt_session, "_dispatch_browser_command", dispatch)
    released = []
    monkeypatch.setattr(lifecycle, "_release_session_backend", lambda task_id, info: released.append(info["cdp_url"]))
    created = []

    def create(task_id, local):
        url = bt_cdp._get_cdp_override_raw()
        if not created:
            assert server._browser_connect("r1", {"url": "http://127.0.0.1:9512"})["result"]["connected"]
        created.append(url)
        return {"session_name": f"s{len(created)}", "cdp_url": url, "bb_session_id": None}
    monkeypatch.setattr(bt_session, "_create_session_for_key", create)

    with _profile_runtime_scope(a, hydrate_secrets=False):
        bt_cdp.set_live_cdp_override("http://127.0.0.1:9511")
        info = bt_session._get_session_info("task-a")
    assert visible_during_close == [("http://127.0.0.1:9511", None)]
    assert released == ["http://127.0.0.1:9511"]
    assert info["cdp_url"] == "http://127.0.0.1:9512" and sessions["task-a"] is info


def test_another_profiles_connect_does_not_invalidate_this_profiles_new_session(profiles, monkeypatch):
    from tools import browser_tool, browser_tool_lifecycle as lifecycle, browser_tool_session as bt_session
    a, b = profiles
    sessions = {}
    monkeypatch.setattr(browser_tool, "_active_sessions", sessions)
    monkeypatch.setattr(lifecycle, "_start_browser_cleanup_thread", lambda: None)
    monkeypatch.setattr(bt_cdp, "_ensure_cdp_supervisor", lambda key: None)
    closed = []
    monkeypatch.setattr(lifecycle, "_cleanup_single_browser_session", closed.append)

    def create(task_id, local):
        with _profile_runtime_scope(b, hydrate_secrets=False):
            bt_cdp.set_live_cdp_override("http://127.0.0.1:9601")
        return {"session_name": "s", "cdp_url": "x"}
    monkeypatch.setattr(bt_session, "_create_session_for_key", create)
    with _profile_runtime_scope(a, hydrate_secrets=False):
        info = bt_session._get_session_info("task-a")
    assert sessions == {"task-a": info} and closed == []
