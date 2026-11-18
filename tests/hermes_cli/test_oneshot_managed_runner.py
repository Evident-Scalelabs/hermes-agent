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
