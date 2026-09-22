"""Context-engine schemas use the same provider normalization as registry tools."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from agent.agent_init import _inject_context_engine_tools


def test_context_engine_conditional_schema_is_sanitized_without_mutating_plugin():
    schema = {"name": "lcm_compile_evidence", "description": "Compile evidence", "parameters": {
        "type": "object", "properties": {"mode": {"type": "string"}, "proposal": {"type": "object"}},
        "allOf": [{"if": {"properties": {"mode": {"const": "proposal"}}},
                   "then": {"required": ["proposal"]}}],
    }}
    original = deepcopy(schema)
    engine = Mock()
    engine.get_tool_schemas.return_value = [schema]
    agent = SimpleNamespace(context_compressor=engine, tools=[], enabled_toolsets=["context_engine"],
                            valid_tool_names=set(), session_id="fixture", platform="cli", model="fixture")
    _inject_context_engine_tools(agent)
    assert "allOf" not in agent.tools[0]["function"]["parameters"]
    assert schema == original
    assert agent.valid_tool_names == {"lcm_compile_evidence"}
    _inject_context_engine_tools(agent)
    assert len(agent.tools) == 1
