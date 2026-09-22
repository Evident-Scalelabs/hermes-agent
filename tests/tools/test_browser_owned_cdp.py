"""Task ownership through the real native command adapter; no remote providers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from unittest.mock import Mock

import pytest

from tools import browser_tool as bt, browser_tool_session as session, browser_tool_lifecycle as lifecycle
from tools import browser_use_cli as retired

_REAL_RETIRED = retired.retired_browser_backend_error
_REAL_BACKEND = retired.get_browser_backend


def test_observation_uses_native_last_navigation_session(monkeypatch):
    monkeypatch.setattr(bt, '_last_active_session_key', {'task': 'task::local'})
    monkeypatch.setattr(bt, '_active_sessions', {'task::local': {'owner_task_id': 'task', 'session_key': 'task::local'}})
    run = Mock(return_value={'success': True})
    monkeypatch.setattr(session, '_run_browser_command', run)
    session.run_browser_command('task', 'eval', ['location.href'])
    assert run.call_args.args[0] == bt._last_session_key('task') == 'task::local'


def test_cdp_close_does_not_create_tab_or_supervisor(monkeypatch):
    supervisor = Mock()
    monkeypatch.setattr(session._cdp, '_ensure_cdp_supervisor', supervisor)
    monkeypatch.setattr(session._cloud, '_get_browser_engine', lambda: 'auto')
    spawn = Mock(return_value={'success': True})
    monkeypatch.setattr(session, '_spawn_and_collect', spawn)
    info = {'session_name': 'owned', 'cdp_url': 'ws://127.0.0.1:1'}
    session._dispatch_browser_command('task', info, 'agent-browser', 'close', [], 1, None)
    supervisor.assert_not_called()
    assert spawn.call_count == 1
    argv = spawn.call_args.args[2]
    assert argv[argv.index('--session') + 1] == info['session_name']
    assert argv[-1] == 'close'


def test_failed_daemon_kill_keeps_recovery_identity(monkeypatch, tmp_path):
    socket = tmp_path / 'agent-browser-owned'
    socket.mkdir()
    (socket / 'owned.pid').write_text('123')
    monkeypatch.setattr(bt, '_socket_safe_tmpdir', lambda: str(tmp_path))
    monkeypatch.setattr(lifecycle, '_kill_verified_daemon', lambda *_: False)
    monkeypatch.setattr(lifecycle, '_pid_exists', lambda _: True)
    lifecycle._release_session_resources('task', {'session_name': 'owned'})
    assert (socket / 'owned.pid').read_text() == '123'


@pytest.mark.parametrize('browser', ["backend: 'off'\n  cloud_provider: camofox", "backend: 'off'"])
def test_retired_camofox_cannot_select_another_controller(monkeypatch, tmp_path, browser):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text('browser:\n  ' + browser + '\n')
    monkeypatch.setenv('CAMOFOX_URL', 'http://127.0.0.1:1')
    monkeypatch.setattr(retired, 'retired_browser_backend_error', _REAL_RETIRED)
    monkeypatch.setattr(retired, 'get_browser_backend', _REAL_BACKEND)
    from tools.browser_camofox import is_camofox_mode
    assert is_camofox_mode() is False
    assert 'Camofox controller is retired' in retired.retired_browser_backend_error()
    assert session._browser_command_preflight()['success'] is False


@pytest.mark.integration
@pytest.mark.live_system_guard_bypass  # Verified daemons detach from their short-lived CLI parent.
@pytest.mark.skipif(os.environ.get('HERMES_E2E_BROWSER') != '1', reason='set HERMES_E2E_BROWSER=1')
def test_real_cdp_tasks_own_tabs_supervisors_and_daemons(monkeypatch):
    chrome_path = shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome_path and Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').is_file():
        chrome_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    if not chrome_path or not shutil.which('agent-browser'):
        pytest.skip('Chrome and pinned agent-browser must be installed')
    from tools.browser_supervisor import SUPERVISOR_REGISTRY
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    # Short paths also fit macOS's 103-byte Unix socket limit.
    with tempfile.TemporaryDirectory(prefix='h-cdp-', dir='/tmp' if os.name != 'nt' else None) as directory:
        root = Path(directory)
        (root / 'config.yaml').write_text("browser:\n  backend: 'off'\n  cloud_provider: local\n")
        token = set_hermes_home_override(root)
        monkeypatch.setenv('HERMES_HOME', str(root))
        monkeypatch.setattr(bt, '_socket_safe_tmpdir', lambda: str(root))
        monkeypatch.setattr(lifecycle, '_start_browser_cleanup_thread', lambda: None)
        monkeypatch.setattr(bt, '_active_sessions', {})
        monkeypatch.setattr(bt, '_last_active_session_key', {})
        profile = root / 'chrome'
        proc = subprocess.Popen([chrome_path, '--headless=new', '--remote-debugging-port=0',
                                 f'--user-data-dir={profile}', '--no-first-run', 'about:blank'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(150):
                if (profile / 'DevToolsActivePort').exists():
                    break
                time.sleep(.1)
            lines = (profile / 'DevToolsActivePort').read_text().splitlines()
            endpoint = f'ws://127.0.0.1:{lines[0]}{lines[1]}'
            monkeypatch.setenv('BROWSER_CDP_URL', endpoint)
            def page_targets():
                with urllib.request.urlopen(f'http://127.0.0.1:{lines[0]}/json/list', timeout=5) as response:
                    return {page['id'] for page in json.load(response) if page['type'] == 'page'}
            initial_targets = page_targets()
            for task in ('owner-a', 'owner-b'):
                result = session.run_browser_command(task, 'open', [f'data:text/html,<title>{task}</title>'])
                assert result['success'], result
            a, b = (bt._active_sessions[key] for key in ('owner-a', 'owner-b'))
            assert a['_cdp_target_id'] != b['_cdp_target_id']
            assert page_targets() == initial_targets | {a['_cdp_target_id'], b['_cdp_target_id']}
            for task, info in (('owner-a', a), ('owner-b', b)):
                observed = session.run_browser_command(task, 'eval', ['document.title'])
                assert observed['data']['result'] == task, observed
                supervisor = SUPERVISOR_REGISTRY.get(task)
                assert supervisor.target_id == info['_cdp_target_id']
                assert supervisor.evaluate_runtime('document.title')['result'] == task
                assert (root / f"agent-browser-{info['session_name']}" / f"{info['session_name']}.pid").exists()
            # Timeout replacement keeps the same owned tab; another task remains unaffected.
            socket = root / f"agent-browser-{a['session_name']}"
            session._discard_timed_out_browser_session('owner-a', a, str(socket))
            resumed = session.run_browser_command('owner-a', 'eval', ['document.title'])
            assert resumed['data']['result'] == 'owner-a', resumed
            # Hard child exit skips atexit: the parent must reap the detached daemon by owner PID.
            child_code = """
import json, os
from tools import browser_tool as bt, browser_tool_session as s
bt._socket_safe_tmpdir = lambda: os.environ['AUDIT_SOCKET_ROOT']
r = s.run_browser_command('child-task', 'open', ['data:text/html,<title>child</title>'])
assert r['success'], r
print(json.dumps(bt._active_sessions['child-task']), flush=True)
os._exit(0)
"""
            child = subprocess.run([sys.executable, '-c', child_code],
                                   env={**os.environ, 'AUDIT_SOCKET_ROOT': str(root)},
                                   capture_output=True, text=True, timeout=30)
            assert child.returncode == 0, child.stderr
            child_info = json.loads(child.stdout.strip().splitlines()[-1])
            child_socket = root / f"agent-browser-{child_info['session_name']}"
            child_pid = int((child_socket / f"{child_info['session_name']}.pid").read_text())
            lifecycle._reap_orphaned_browser_sessions()
            assert not lifecycle._pid_exists(child_pid)
            assert not child_socket.exists()
            tabs = session.run_browser_command('owner-b', 'tab', ['list'])
            assert child_info['_cdp_target_id'] not in json.dumps(tabs), tabs
            assert session.run_browser_command('owner-b', 'eval', ['document.title'])['data']['result'] == 'owner-b'
            with monkeypatch.context() as interrupted:
                interrupted.setattr('tools.interrupt.is_interrupted', lambda: True)
                lifecycle.cleanup_browser('owner-a')
            assert session.run_browser_command('owner-b', 'eval', ['document.title'])['data']['result'] == 'owner-b'
            assert SUPERVISOR_REGISTRY.get('owner-a') is None
            lifecycle.cleanup_browser('owner-b')
            assert page_targets() == initial_targets
        finally:
            try:
                for task in ('owner-a', 'owner-b'):
                    lifecycle.cleanup_browser(task)
            finally:
                proc.terminate()
                proc.wait(timeout=10)
                reset_hermes_home_override(token)


def test_orphan_reaper_leaves_other_live_owner_even_when_idle(monkeypatch, tmp_path):
    monkeypatch.setattr(lifecycle, '_owner_pid_alive', lambda *_: (os.getpid() + 1, True))
    monkeypatch.setattr(lifecycle, '_socket_dir_idle_seconds', lambda *_: bt.BROWSER_ORPHAN_GRACE_SECONDS + 1)
    probe = Mock()
    monkeypatch.setattr(lifecycle, '_verify_reapable_browser_daemon', probe)
    assert lifecycle._reap_socket_dir(str(tmp_path), 'cdp-other-owner', set()) is False
    probe.assert_not_called()


def test_close_without_owned_session_does_not_spawn(monkeypatch):
    monkeypatch.setattr(bt, '_active_sessions', {})
    preflight = Mock()
    monkeypatch.setattr(session, '_browser_command_preflight', preflight)
    assert session.run_browser_command('gone-task', 'close')['success']
    preflight.assert_not_called()


def test_orphan_tab_close_failure_keeps_daemon_and_metadata(monkeypatch, tmp_path):
    (tmp_path / 'cdp-dead.pid').write_text('123')
    monkeypatch.setattr(lifecycle, '_owner_pid_alive', lambda *_: (456, False))
    monkeypatch.setattr('gateway.status._pid_exists', lambda _: True)
    monkeypatch.setattr(lifecycle, '_verify_reapable_browser_daemon', lambda *_: True)
    monkeypatch.setattr(lifecycle, '_close_orphan_tab', lambda *_: False)
    kill = Mock()
    monkeypatch.setattr(lifecycle, '_terminate_verified_daemon', kill)
    assert lifecycle._reap_socket_dir(str(tmp_path), 'cdp-dead', set()) is False
    assert (tmp_path / 'cdp-dead.pid').exists()
    kill.assert_not_called()


@pytest.mark.parametrize('failed_command', ['tab', 'close'])
def test_cleanup_false_result_warns_and_preserves_owner(monkeypatch, caplog, failed_command):
    info = {'session_name': 'owned', 'cdp_url': 'ws://127.0.0.1:1', '_cdp_target_id': 'task-target'}
    monkeypatch.setattr(bt, '_active_sessions', {'task': info})
    monkeypatch.setattr(session, '_run_browser_command', lambda _task, command, *_a, **_k:
                        {'success': command != failed_command, 'error': 'connection lost'})
    assert lifecycle.cleanup_browser('task') is False
    assert bt._active_sessions['task'] is info
    assert 'ownership retained' in caplog.text
