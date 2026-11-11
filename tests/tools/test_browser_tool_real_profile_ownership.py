"""Real-profile Chrome and its children stay owned across crash and startup cleanup.

These POSIX tests run the real launch/teardown seam with a disposable executable,
never the user's browser or profile. Real orphan cleanup needs the same live-system
guard bypass as the native owner-death supervisor tests.
"""

import contextlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

import psutil
import pytest

from tests.waiting import wait_until


pytestmark = pytest.mark.platforms("posix")
ROOT = Path(__file__).resolve().parents[2]

FAKE_CHROME = """
import json, os, subprocess, sys, threading
from pathlib import Path

directory = Path(next(arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--user-data-dir=')))
child = subprocess.Popen([sys.executable, '-c', 'import threading; threading.Event().wait(300)'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
(directory / 'browser.json').write_text(json.dumps({
    'pid': os.getpid(), 'child': child.pid, 'argv': sys.argv[1:], 'home': os.environ.get('HERMES_HOME'),
}), encoding='utf-8')
if os.environ['REAL_PROFILE_FIXTURE_MODE'] == 'startup_failure':
    raise SystemExit(17)
(directory / 'DevToolsActivePort').write_text('41999\\n/devtools/browser/fixture\\n', encoding='utf-8')
threading.Event().wait(300)
"""

OWNER = """
import json, sys, threading
from pathlib import Path
from types import SimpleNamespace
from tools import browser_tool_real_profile as real_profile
from tools.environments.local import served_profile_child_env

binary, directory, profile, mode, receipt = sys.argv[1:]
browser_env = served_profile_child_env(target_home=profile, inherit_credentials=False)
browser_env['REAL_PROFILE_FIXTURE_MODE'] = mode
state = SimpleNamespace(_real_profile_chrome_procs=[], _build_browser_env=lambda: browser_env)
real_profile._origin = lambda: state
real_profile._session._ensure_screen_for_headed_chromium = lambda: None
real_profile._cloud._is_headed_mode = lambda: False
port, error = real_profile._launch_real_profile_chrome(binary, directory)
if mode != 'owner_death':
    real_profile._terminate_real_profile_chrome()
target = Path(receipt)
temporary = target.with_suffix('.tmp')
temporary.write_text(json.dumps({'port': port, 'error': error, 'tracked': len(state._real_profile_chrome_procs)}), encoding='utf-8')
temporary.replace(target)
if mode == 'owner_death':
    threading.Event().wait(300)
"""


def _alive(pid):
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


@contextlib.contextmanager
def _owner(tmp_path, mode):
    launch = tmp_path / "launch"
    profile = launch / "profiles" / "served"
    profile.mkdir(parents=True)
    (launch / "config.yaml").write_text("{}\n", encoding="utf-8")
    (profile / "config.yaml").write_text("{}\n", encoding="utf-8")
    directory = tmp_path / "profile-copy"
    directory.mkdir()
    chrome = tmp_path / "chrome.py"
    chrome.write_text(FAKE_CHROME, encoding="utf-8")
    executable = tmp_path / "chrome"
    executable.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(chrome))} \"$@\"\n", encoding="utf-8",
    )
    executable.chmod(0o700)
    receipt = tmp_path / "owner.json"
    log = tmp_path / "owner.log"
    with log.open("w", encoding="utf-8") as stream:
        owner = subprocess.Popen(
            [sys.executable, "-c", OWNER, str(executable), str(directory), str(profile), mode, str(receipt)],
            cwd=ROOT, env={**os.environ, "HERMES_HOME": str(launch)},
            stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
        )
    browser = None
    try:
        wait_until(lambda: receipt.exists() or owner.poll() is not None, timeout=15, what="real-profile launch result")
        assert receipt.exists(), log.read_text(encoding="utf-8")
        browser = json.loads((directory / "browser.json").read_text(encoding="utf-8"))
        result = json.loads(receipt.read_text(encoding="utf-8"))
        assert browser["home"] == str(profile)
        assert f"--user-data-dir={directory}" in browser["argv"]
        assert "--use-mock-keychain" not in browser["argv"]
        assert "--password-store=basic" not in browser["argv"]
        yield owner, browser, result
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=10)
        if browser is None and (directory / "browser.json").exists():
            browser = json.loads((directory / "browser.json").read_text(encoding="utf-8"))
        if browser is not None:
            for pid in (browser["pid"], browser["child"]):
                with contextlib.suppress(ProcessLookupError):
                    if _alive(pid):
                        os.kill(pid, signal.SIGKILL)


@pytest.mark.live_system_guard_bypass
def test_real_profile_browser_tree_dies_when_hermes_owner_is_killed(tmp_path):
    with _owner(tmp_path, "owner_death") as (owner, browser, result):
        assert result == {"port": 41999, "error": None, "tracked": 1}
        assert _alive(browser["pid"]) and _alive(browser["child"])
        owner.kill()
        owner.wait(timeout=10)
        wait_until(lambda: not _alive(browser["pid"]) and not _alive(browser["child"]), timeout=15,
                   what="real-profile Chrome tree to exit with its owner")


@pytest.mark.live_system_guard_bypass
@pytest.mark.parametrize("mode", ["normal_cleanup", "startup_failure"])
def test_real_profile_teardown_reaps_children_and_clears_tracked_processes(tmp_path, mode):
    with _owner(tmp_path, mode) as (owner, browser, result):
        owner.wait(timeout=15)
        assert result["tracked"] == 0
        if mode == "startup_failure":
            assert result["port"] is None and "Chrome exited during startup" in result["error"]
        else:
            assert result["port"] == 41999 and result["error"] is None
        wait_until(lambda: not _alive(browser["pid"]) and not _alive(browser["child"]), timeout=15,
                   what="normal/startup-failure teardown to reap the Chrome tree")
