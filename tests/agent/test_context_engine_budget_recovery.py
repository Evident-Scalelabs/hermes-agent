"""Plugin compactions rearm the native retry budget only on confirmed headroom.

The host used the built-in compressor's private progress flag to arm recovery.
LCM implements ContextEngine without that flag, so successful compactions exhausted
the same-turn cap. Exercise real compression commits through run_conversation().
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.context_engine import ContextEngine
from agent.turn_usage import record_response_usage
from hermes_state import SessionDB
from run_agent import AIAgent


THRESHOLD = 50_000
IMAGE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII="


class PluginEngine(ContextEngine):
    """Only the documented engine protocol; no built-in progress/verdict methods."""

    name = "fixture-plugin"
    context_length = 200_000
    threshold_tokens = THRESHOLD
    emit_automatic_compaction_status = False

    def __init__(self):
        self.compactions = []

    def should_compress(self, prompt_tokens=None):
        return (prompt_tokens or self.last_prompt_tokens) >= self.threshold_tokens

    def compress(self, messages, **_kwargs):
        self.compactions.append(len(messages))
        self.compression_count += 1
        return [
            dict(message, content="[retained evidence summary]")
            if message.get("role") == "tool" and len(str(message.get("content"))) > 5_000
            else dict(message)
            for message in messages
        ]

    def update_from_response(self, usage):
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)
        self.last_total_tokens = usage.get("total_tokens", 0)


def _response(index, prompt_tokens, *, final=False):
    call = SimpleNamespace(
        id=f"call_{index}", type="function",
        function=SimpleNamespace(name="web_search", arguments=json.dumps({"query": f"evidence {index}"})),
    )
    message = SimpleNamespace(
        content="done" if final else None, reasoning_content=None, reasoning=None,
        tool_calls=None if final else [call],
    )
    usage = None if prompt_tokens is None else SimpleNamespace(
        prompt_tokens=prompt_tokens, completion_tokens=1, total_tokens=prompt_tokens + 1,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop" if final else "tool_calls")],
        model="test/model", usage=usage,
    )


@pytest.fixture
def agent(tmp_path):
    tools = [{"type": "function", "function": {
        "name": "web_search", "description": "Read saved evidence",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    }}]
    with (
        patch("model_tools.get_tool_definitions", return_value=tools),
        patch("model_tools.check_toolset_requirements", return_value={}),
        patch("agent.process_bootstrap.OpenAI"),
        patch("agent.model_metadata.get_model_context_length", return_value=200_000),
        patch("agent.context_compressor.get_model_context_length", return_value=200_000),
    ):
        instance = AIAgent(
            api_key="test-key", base_url="https://openrouter.ai/api/v1", model="test/model",
            quiet_mode=True, skip_context_files=True, skip_memory=True, max_iterations=20,
            session_db=SessionDB(db_path=tmp_path / "state.db"), session_id="plugin-recovery",
        )
    instance.client = MagicMock()
    instance.context_compressor = PluginEngine()
    instance._cached_system_prompt = "Use the saved evidence and finish the requested report."
    instance._use_prompt_caching = False
    instance._disable_streaming = True
    instance._compression_feasibility_checked = True
    instance.compression_enabled = True
    instance.compression_in_place = True
    instance.tool_delay = 0
    instance.save_trajectories = False
    try:
        yield instance
    finally:
        instance.close()


@pytest.mark.parametrize("site_url,image_count", [("https://school.example", 0), ("https://shop.example", 12)])
@pytest.mark.parametrize("prompt_tokens", [THRESHOLD - 1, None, THRESHOLD])
def test_plugin_turn_compacts_past_cap_only_after_provider_confirmed_recovery(
    agent, site_url, image_count, prompt_tokens,
):
    engine = agent.context_compressor
    agent.max_compression_attempts = 3
    agent.client.chat.completions.create.side_effect = [
        *[_response(index, prompt_tokens) for index in range(8)],
        _response(8, prompt_tokens, final=True),
    ]
    ask = [{"type": "text", "text": f"Finish the report for {site_url}."}] + [
        {"type": "image_url", "image_url": {"url": IMAGE, "detail": "high"}}
        for _ in range(image_count)
    ]
    with patch("model_tools.handle_function_call", return_value=json.dumps({"evidence": "x" * 60_000})):
        result = agent.run_conversation(ask)

    assert result["completed"] is True
    assert result["final_response"] == "done"
    if prompt_tokens == THRESHOLD - 1:
        assert len(engine.compactions) > agent.max_compression_attempts
    else:
        assert len(engine.compactions) <= agent.max_compression_attempts
    assert any(message.get("content") == ask for message in result["messages"])
    # Compaction refreshes dynamic schemas; the configured search tool must remain available.
    assert all(
        "web_search" in {tool["function"]["name"] for tool in call.kwargs["tools"]}
        for call in agent.client.chat.completions.create.call_args_list
    )


@pytest.mark.parametrize("first_usage", [None, THRESHOLD, THRESHOLD - 1])
def test_plugin_compaction_verdict_is_consumed_by_the_first_response(agent, first_usage):
    engine = agent.context_compressor
    engine._verify_compaction_cleared_threshold = True
    engine.awaiting_real_usage_after_compression = True
    first = record_response_usage(
        agent, _response(0, first_usage), messages=[], api_call_count=1,
        api_duration=0, compression_attempts=3, max_compression_attempts=3,
    )
    assert first.rearmed is (first_usage == THRESHOLD - 1)
    assert engine.awaiting_real_usage_after_compression is False
    later = record_response_usage(
        agent, _response(1, THRESHOLD - 1), messages=[], api_call_count=2,
        api_duration=0, compression_attempts=3, max_compression_attempts=3,
    )
    assert later.rearmed is False
    assert later.compression_attempts == 3
