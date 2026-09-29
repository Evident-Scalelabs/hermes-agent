"""Tests for ``agent/turn_api_call.py::handle_api_interrupt`` — the plain (non-redirect)
interrupt that lands mid provider call and records the streamed partial as the interrupted
assistant row."""
from __future__ import annotations

import threading
import time

import pytest

from agent.agent_runtime_helpers import _INTERRUPTED_PLACEHOLDER
from agent.repetition_guard import REPETITION_LOOP_INTERRUPTED
from agent.turn_api_call import handle_api_interrupt
from agent.turn_retry_state import TurnRetryState
from run_agent import AIAgent


def _bare_agent(streamed: str) -> AIAgent:
    agent = object.__new__(AIAgent)
    agent._pending_redirect = None
    agent._pending_redirect_lock = threading.Lock()
    agent._interrupt_requested = False
    agent._interrupt_message = None
    agent._current_streamed_assistant_text = streamed
    agent._strip_think_blocks = lambda content: content
    agent.quiet_mode = True
    agent.log_prefix = ""
    agent.thinking_callback = None
    agent._print_fn = lambda *args, **kwargs: None
    agent._persist_session = lambda *args, **kwargs: None
    return agent


def _interrupt(streamed: str):
    messages = [{"role": "user", "content": "start"}]
    verdict = handle_api_interrupt(
        _bare_agent(streamed), _retry=TurnRetryState(), thinking_spinner=None, messages=messages,
        conversation_history=[], api_start_time=time.time(), interrupted=False, final_response=None,
    )
    return messages, verdict


def test_repetition_dominated_partial_is_not_kept_as_the_interrupted_row():
    """A looped partial replayed as the interrupted assistant row re-seeds the loop on the next
    turn (#112764): the row keeps the neutral placeholder and the user is told what happened."""
    looped = "I. " * 1941

    messages, verdict = _interrupt(looped)

    # Same hidden shape as the redirect placeholder: no visible bubble in transcript replays.
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == ""
    assert messages[-1]["display_kind"] == "hidden"
    assert messages[-1]["api_content"] == _INTERRUPTED_PLACEHOLDER
    assert verdict.final_response == REPETITION_LOOP_INTERRUPTED
    assert "I. I. I." not in verdict.final_response


def test_distinct_batch_rows_are_not_mistaken_for_a_loop():
    """Legitimately repetitive output (distinct INSERT rows sharing a long prefix) trips the
    window scan but is not a runaway loop: the partial must stay the interrupted row and must
    not be relabelled as a degenerate reply."""
    rows = "\n".join(
        f"INSERT INTO users (id, name, email, created_at) VALUES ({i}, 'user{i}', 'user{i}@example.com', NOW());"
        for i in range(12)
    )
    messages, verdict = _interrupt(rows)

    assert (messages[-1]["role"], messages[-1]["content"]) == ("assistant", rows)
    assert verdict.final_response == rows


def test_ordinary_partial_is_kept_as_the_interrupted_row():
    messages, verdict = _interrupt("Visible draft.")

    assert (messages[-1]["role"], messages[-1]["content"]) == ("assistant", "Visible draft.")
    assert verdict.final_response == "Visible draft."


@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("failure", [None, InterruptedError, RuntimeError])
def test_model_request_protects_browser_until_transport_finishes(monkeypatch, streaming, failure):
    from types import SimpleNamespace
    from agent import turn_api_call, relay_llm
    from tools import browser_tool as bt, browser_tool_lifecycle as lifecycle
    import hermes_cli.middleware

    monkeypatch.setattr(bt, "_session_last_activity", {"request-task": 0, "request-task::local": 0})
    monkeypatch.setattr(bt, "_model_request_counts", {})
    monkeypatch.setattr(bt, "_idle_cleanup_claims", set())
    closed = []
    monkeypatch.setattr(lifecycle, "cleanup_browser", lambda task: closed.append(task))
    monkeypatch.setattr(lifecycle, "_human_holds_shared_browser", lambda task: False)
    monkeypatch.setattr(turn_api_call, "_should_stream", lambda agent: streaming)
    monkeypatch.setattr(hermes_cli.middleware, "run_llm_execution_middleware", lambda args, call, **kw: call(args))
    monkeypatch.setattr(relay_llm, "execute", lambda args, call, **kw: call(args))

    def transport(*args, **kwargs):
        lifecycle._cleanup_inactive_browser_sessions()
        assert closed == []
        assert bt._model_request_counts == {"request-task": 1}
        if failure:
            raise failure("transport ended")
        return "response"

    agent = SimpleNamespace(
        api_mode="chat", session_id="different-session", platform="test", model="test", provider="test",
        base_url="", _interruptible_streaming_api_call=transport, _interruptible_api_call=transport,
        _model_request_active=threading.Event(), _has_pending_redirect=lambda: False,
    )
    kwargs = dict(api_kwargs={}, _original_api_kwargs={}, _llm_middleware_trace=[],
                  _moa_prepared_request=None, _retry=None, thinking_spinner=None, retry_count=0,
                  api_call_count=1, api_request_id="request", effective_task_id="request-task",
                  turn_id="turn", interrupted=False)
    if failure:
        with pytest.raises(failure, match="transport ended"):
            turn_api_call.perform_api_call(agent, **kwargs)
    else:
        assert turn_api_call.perform_api_call(agent, **kwargs).response == "response"
    assert bt._model_request_counts == {}
    assert not agent._model_request_active.is_set()
    lifecycle._cleanup_inactive_browser_sessions()
    assert set(closed) == {"request-task", "request-task::local"}
