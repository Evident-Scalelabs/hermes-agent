"""External managed profile runners keep their in-process hooks and usage ledger."""

import json

import pytest

from hermes_cli import oneshot


@pytest.mark.parametrize("completed, expected_code", [(True, 0), (False, 2)])
def test_managed_runner_preserves_outcome_and_usage(monkeypatch, tmp_path, capsys,
                                                   completed, expected_code):
    seen = {}

    def run_agent(prompt, **kwargs):
        seen.update(prompt=prompt, **kwargs)
        return "managed result", {"completed": completed, "api_calls": 1,
                                  "model": "test-model", "provider": "openai",
                                  "session_id": "managed-session"}

    monkeypatch.setattr(oneshot, "_run_agent", run_agent)
    usage = tmp_path / "usage.json"
    code = oneshot.run_oneshot("managed prompt", model="test-model", provider="openai",
                               resume="managed-session", usage_file=str(usage))
    assert code == expected_code
    assert capsys.readouterr().out == "managed result\n"
    assert seen["prompt"] == "managed prompt" and seen["resume"] == "managed-session"
    assert seen["ledger"] is True
    report = json.loads(usage.read_text())
    assert report["completed"] is completed and report["api_calls"] == 1
    assert report["session_id"] == "managed-session"


def test_managed_runner_ledger_reads_auxiliary_usage_through_agent_storage(monkeypatch, tmp_path):
    from hermes_state import SessionDB
    from persistence.conversation.usage import TokenCounts

    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session(session_id="s1", source="cli")
    store = db._store
    store.usage.record_auxiliary_usage("s1", "vision", tokens=TokenCounts(input_tokens=500), estimated_cost_usd=0.5)

    class _Agent:
        persistence = store
        session_id = "s1"

        def __init__(self, **_kwargs):
            pass

        def run_conversation(self, _prompt, conversation_history=None):
            store.usage.record_auxiliary_usage("s1", "title_generation", tokens=TokenCounts(input_tokens=40),
                                               estimated_cost_usd=0.001)
            return {"final_response": "ok", "session_id": "s1"}

        def close(self):
            pass

    monkeypatch.setattr(oneshot, "_create_session_db_for_oneshot", lambda: db)
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"model": {"default": "m", "provider": "openrouter"}})
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider",
                        lambda **_kw: {"api_key": "k", "base_url": None, "provider": "openrouter",
                                       "requested_provider": "openrouter", "api_mode": "chat",
                                       "credential_pool": None})
    monkeypatch.setattr("hermes_cli.tools_config._get_platform_tools", lambda _cfg, _p: [])
    monkeypatch.setattr("hermes_cli.mcp_startup.ensure_mcp_discovery_before_agent_build", lambda **_kw: None)
    monkeypatch.setattr("run_agent.AIAgent", _Agent)

    _text, result = oneshot._run_agent("hello", resume="s1", ledger=True)

    assert set(result["auxiliary_usage"]) == {"title_generation"}
    assert result["auxiliary_usage"]["title_generation"]["input_tokens"] == 40
