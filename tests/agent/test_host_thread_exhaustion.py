"""A local thread allocation failure cannot be repaired by model failover."""

from unittest.mock import MagicMock

import httpx
import openai
import pytest

from agent.error_classifier import FailoverReason, classify_api_error
from agent.error_surface import build_error_surface_from_exception, build_error_surface_from_result


@pytest.mark.parametrize("message", ["can't start new thread", "cannot start new thread"])
def test_host_thread_failure_is_terminal_and_distinct_from_an_upstream_error(message):
    failure = RuntimeError(message)
    classified = classify_api_error(failure, provider="openai", model="primary")

    assert classified.reason == FailoverReason.host_resource_exhausted
    assert not classified.retryable
    assert not classified.should_fallback
    assert not classified.should_rotate_credential
    assert build_error_surface_from_exception(failure) == {
        "layer": "gateway", "code": "host_resource_exhausted", "retryable": False,
    }

    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    upstream = openai.InternalServerError(
        message, response=httpx.Response(500, request=request), body={"message": message},
    )
    assert classify_api_error(upstream).reason == FailoverReason.server_error


def test_real_turn_stops_after_one_host_failure_and_keeps_its_pending_fallback():
    from run_agent import AIAgent

    agent = AIAgent(
        api_key="test-key", provider="openai", model="gpt-5.5", api_mode="chat_completions",
        base_url="http://127.0.0.1:9/v1", enabled_toolsets=[], quiet_mode=True,
        skip_context_files=True, skip_memory=True, skip_background_review=True, save_trajectories=False,
        fallback_model={"provider": "openai", "model": "fallback-test", "api_key": "test-key"},
    )
    # Only the external provider SDK is replaced; the full turn, classifier,
    # recovery, persistence and cleanup run against the isolated test home.
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("can't start new thread")
    agent.client = client
    agent.compression_enabled = False
    assert agent._has_pending_fallback()

    result = agent.run_conversation("Evaluate the supplied page.")

    assert client.chat.completions.create.call_count == 1
    assert result["failed"] is True
    assert result["failure_reason"] == "host_resource_exhausted"
    assert result["failure_retryable"] is False
    assert agent.model == "gpt-5.5"
    assert agent._has_pending_fallback()
    assert "switching models cannot free that capacity" in result["final_response"]
    assert "Provider said" not in result["final_response"]
    surface = build_error_surface_from_result(result)
    assert surface["layer"] == "gateway" and surface["code"] == "host_resource_exhausted"
