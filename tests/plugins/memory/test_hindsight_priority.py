"""Broad recall must carry priority corrections without changing bank or source wording."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest_plugins = ("tests.plugins.memory.test_hindsight_provider",)


def response(items):
    return SimpleNamespace(model_dump=lambda **kwargs: {"results": items})


@pytest.mark.parametrize('prefetch', [False, True])
def test_broad_recall_carries_source_correction_within_budget(provider_with_config, prefetch):
    p = provider_with_config(recall_tags=['scope:site'], recall_tags_match='all_strict',
                             recall_priority_tags=['kind:correction'])
    correction = {'id': 'corrected', 'text': 'Evident assessment, observed 2026-10-14: terms were not established on the inspected offer page; other pages were not inspected.',
                  'type': 'world', 'document_id': 'reviewed-source', 'tags': ['scope:site', 'kind:correction']}
    original = {'id': 'original', 'text': 'An older assessment of incomplete terms.'}
    p._client.arecall = AsyncMock(side_effect=lambda **kw: response([correction] if 'kind:correction' in kw['tags'] else [original, correction]))
    try:
        if prefetch:
            result = p._recall('What matters about the offer?', prefetch=True)
        else:
            result = json.loads(p.handle_tool_call('hindsight_recall', {'query': 'What matters about the offer?'}))['result']
        assert result['results'][0]['text'] == correction['text']
        assert [r['id'] for r in result['results']] == ['corrected', 'original']
        calls = [c.kwargs for c in p._client.arecall.call_args_list]
        assert len(calls) == 2
        assert sum(c['max_tokens'] for c in calls) == (1024 if prefetch else 4096)
        assert all(c['bank_id'] == p._bank_id and c['tags_match'] == 'all_strict' for c in calls)
        assert calls[1]['tags'] == ['scope:site', 'kind:correction']
        assert calls[1]['types'] == ['world', 'experience']
        assert result['priority_recall']['state'] == 'complete'
    finally:
        p.shutdown()


def test_failed_priority_preserves_primary_and_source_view_stays_exact(provider_with_config, caplog):
    p = provider_with_config(recall_tags=['scope:site'], recall_tags_match='all_strict',
                             recall_priority_tags=['kind:correction'])
    async def recall(**kwargs):
        if 'kind:correction' in kwargs['tags']:
            raise TimeoutError('private details must not enter the warning')
        return response([{'id': 'kept', 'text': 'Dated original assessment'}])
    p._client.arecall = AsyncMock(side_effect=recall)
    try:
        result = json.loads(p.handle_tool_call('hindsight_recall', {'query': 'Which terms matter?', 'tags': ['topic:client']}))['result']
        assert result['results'][0]['id'] == 'kept'
        assert result['priority_recall']['state'] == 'partial'
        assert 'TimeoutError' in caplog.text and 'private details' not in caplog.text
        assert all(c.kwargs['tags'][:2] == ['scope:site', 'topic:client'] for c in p._client.arecall.call_args_list)
        p._client.arecall.reset_mock()
        p.handle_tool_call('hindsight_recall', {'query': 'What did the source say?', 'view': 'sources'})
        p._client.arecall.assert_awaited_once()
        assert p._client.arecall.call_args.kwargs['include_chunks'] is True
    finally:
        p.shutdown()
