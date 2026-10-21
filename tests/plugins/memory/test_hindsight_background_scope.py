"""Hindsight background work retains its initiating profile's secret scope."""
import json
import sys
import threading
from types import SimpleNamespace

import pytest

from plugins.memory.hindsight import HindsightMemoryProvider, _WRITER_SENTINEL


class TestMultiplexBackgroundScope:
    """Under multiplex_profiles get_secret fails closed on an unscoped thread;
    the writer / daemon-start threads are spawned from a scoped context and
    must carry it along (#92608, #94933)."""

    @pytest.fixture()
    def scoped_embedded(self, tmp_path, monkeypatch):
        from agent.secret_scope import (
            build_profile_secret_scope, reset_secret_scope, set_multiplex_active, set_secret_scope,
        )
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override

        created = []

        class FakeHindsightEmbedded:
            def __init__(self, **kwargs):
                created.append(kwargs["llm_api_key"])
                self._manager = SimpleNamespace(is_running=lambda profile: False, stop=lambda profile: None)
                self._ensure_started = lambda: None

        dem = SimpleNamespace(console=None)
        monkeypatch.setitem(sys.modules, "hindsight", SimpleNamespace(HindsightEmbedded=FakeHindsightEmbedded))
        monkeypatch.setitem(sys.modules, "hindsight_embed", SimpleNamespace(daemon_embed_manager=dem))
        monkeypatch.setitem(sys.modules, "hindsight_embed.daemon_embed_manager", dem)
        monkeypatch.setattr("plugins.memory.hindsight._check_local_runtime", lambda: (True, ""))
        # This fake daemon tests secret propagation, independently of PostgreSQL's root guard.
        monkeypatch.setattr("plugins.memory.hindsight.os.geteuid", lambda: 1000, raising=False)

        home = tmp_path / "profiles" / "p1"
        (home / "hindsight").mkdir(parents=True)
        (home / ".env").write_text("HINDSIGHT_LLM_API_KEY=p1-secret\n")
        (home / "hindsight" / "config.json").write_text(json.dumps(
            {"mode": "local_embedded", "llm_provider": "openai", "llm_model": "m", "memory_mode": "hybrid"}
        ))
        # Enter the profile scope the way gateway _profile_runtime_scope does.
        set_multiplex_active(True)
        monkeypatch.setattr("plugins.memory.hindsight.get_hermes_home", lambda: home)
        home_tok = set_hermes_home_override(str(home))
        scope_tok = set_secret_scope(build_profile_secret_scope(home))
        yield created, home
        set_multiplex_active(False)
        reset_secret_scope(scope_tok)
        reset_hermes_home_override(home_tok)

    def test_writer_thread_resolves_profile_secret(self, scoped_embedded):
        created, _home = scoped_embedded
        p = HindsightMemoryProvider()
        p._mode = "local_embedded"
        p._config = {"profile": "hermes", "llm_provider": "openai", "llm_model": "m"}
        p._ensure_writer()
        p._retain_queue.put(p._get_client)   # real body: get_secret(HINDSIGHT_LLM_API_KEY)
        p._retain_queue.put(_WRITER_SENTINEL)
        p._writer_thread.join(timeout=5)
        assert created == ["p1-secret"]

    def test_daemon_start_thread_resolves_profile_secret(self, scoped_embedded):
        created, home = scoped_embedded
        p = HindsightMemoryProvider()
        p.initialize(session_id="s1", hermes_home=str(home), platform="cli")
        for t in threading.enumerate():
            if t.name == "hindsight-daemon-start":
                t.join(timeout=5)
        assert created == ["p1-secret"]
        assert "Daemon started successfully" in (home / "logs" / "hindsight-embed.log").read_text()
