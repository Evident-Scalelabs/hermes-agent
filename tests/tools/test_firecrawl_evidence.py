import asyncio
import hashlib
from pathlib import Path
from unittest.mock import patch
import pytest
from plugins.web.firecrawl import provider
from tools.web_tools_truncate import _trim_results, _truncate_results


def test_firecrawl_preserves_full_page_options_and_evidence():
    seen = {}
    class Client:
        def scrape(self, **kwargs):
            seen.update(kwargs)
            return {'markdown': 'Offer and disclosure', 'html': '<h1>Offer</h1><footer>Disclosure</footer>',
                    'metadata': {'title': 'Offer', 'sourceURL': 'https://example.com/offer', 'statusCode': 200}}
    with patch.object(provider, '_get_firecrawl_client', return_value=Client()) as client, \
         patch.object(provider, 'check_website_access', return_value=None), \
         patch.object(provider, 'is_safe_url', return_value=True), \
         patch('tools.web_tools._load_web_config', return_value={'firecrawl': {'only_main_content': False, 'max_age': 0}}):
        result = asyncio.run(provider._scrape_one('https://example.com/offer', ['markdown', 'html'], None))
    client.assert_called_once_with('extract')
    _truncate_results([result], 2000, {'pages_truncated': 0, 'truncation_metrics': []})
    projected = _trim_results([result])[0]
    assert seen['only_main_content'] is False and seen['max_age'] == 0
    assert projected['html'].endswith('<footer>Disclosure</footer>')
    assert projected['metadata']['statusCode'] == 200
    assert projected['provider'] == 'firecrawl'
    assert projected['truncated'] is False


def test_keyless_firecrawl_preserves_full_page_options():
    client = provider._KeylessFirecrawlClient()
    with patch.object(client, '_post', return_value={}) as post:
        client.scrape(url='https://example.com', formats=['markdown', 'html'],
                      only_main_content=False, max_age=0, timeout=60_000)
    post.assert_called_once_with('/v2/scrape', {
        'url': 'https://example.com', 'formats': ['markdown', 'html'],
        'onlyMainContent': False, 'maxAge': 0, 'timeout': 60_000,
    })


def test_firecrawl_cache_separates_full_page_options_and_honors_freshness(tmp_path, monkeypatch):
    from tools import web_result_cache as cache

    monkeypatch.setattr(cache, '_cache_dir', lambda: tmp_path)
    config = {'firecrawl': {'only_main_content': False}}
    monkeypatch.setattr(cache, '_web_config', lambda: config)
    url = 'https://example.com/offer'
    cache.extract_cache_put(url, 'whole page', provider='firecrawl')
    assert cache.extract_cache_get(url, provider='firecrawl')['content'] == 'whole page'
    config['firecrawl']['only_main_content'] = True
    assert cache.extract_cache_get(url, provider='firecrawl') is None
    config['firecrawl']['max_age'] = 0
    cache.extract_cache_put(url, 'fresh whole page', provider='firecrawl')
    assert cache.extract_cache_get(url, provider='firecrawl') is None


def test_truncated_html_keeps_complete_artifact_and_matching_hash():
    html = '<p>Disclosure</p>\n' * 200
    result = {'url': 'https://example.com/offer', 'content': 'Offer', 'html': html}
    _truncate_results([result], 2000, {'pages_truncated': 0, 'truncation_metrics': []})
    projected = _trim_results([result])[0]
    artifact = projected['htmlArtifact']
    assert Path(artifact['path']).read_text(encoding='utf-8') == html
    assert artifact['sha256'] == 'sha256:' + hashlib.sha256(html.encode()).hexdigest()
    assert projected['htmlTruncated'] is True
    assert projected['truncated'] is False


@pytest.mark.parametrize('with_final_url', [True, False])
def test_typed_sdk_document_keeps_fetched_url_and_requested_url_distinct(with_final_url):
    pytest.importorskip('firecrawl')
    from firecrawl.v2.types import Document
    from firecrawl.v2.utils.normalize import normalize_document_input

    requested = 'https://example.com/start?campaign=one'
    final = 'https://example.com/offer?campaign=two&term=three'
    metadata = {'sourceURL': requested if with_final_url else final,
                'statusCode': 200, 'cachedAt': '2026-10-14T00:00:00Z'}
    if with_final_url:
        metadata['url'] = final
    document = Document(**normalize_document_input({
        'markdown': 'Offer', 'html': '<h1>Offer</h1>', 'metadata': metadata,
    }))
    class Client:
        def scrape(self, **kwargs):
            return document
    with patch.object(provider, '_get_firecrawl_client', return_value=Client()), \
         patch.object(provider, 'check_website_access', return_value=None), \
         patch.object(provider, 'is_safe_url', return_value=True) as safe_url:
        result = asyncio.run(provider._scrape_one(requested, ['markdown', 'html'], None))
    safe_url.assert_called_once_with(final)
    projected = _trim_results([result])[0]
    assert projected['url'] == final and projected['requestedUrl'] == requested
    assert projected['metadata']['source_url'] == metadata['sourceURL']
    assert projected['metadata']['status_code'] == 200
    assert projected['metadata']['cached_at'] == '2026-10-14T00:00:00Z'


def test_typed_sdk_document_cannot_return_content_from_blocked_redirect():
    pytest.importorskip('firecrawl')
    from firecrawl.v2.types import Document
    from firecrawl.v2.utils.normalize import normalize_document_input

    requested, final = 'https://example.com/start', 'https://blocked.example/private?keep=query'
    document = Document(**normalize_document_input({
        'markdown': 'Blocked content', 'html': '<h1>Blocked content</h1>',
        'metadata': {'sourceURL': requested, 'url': final, 'statusCode': 200},
    }))
    blocked = {'host': 'blocked.example', 'rule': 'blocked.example',
               'source': 'operator', 'message': 'Blocked by policy'}
    class Client:
        def scrape(self, **kwargs):
            return document
    with patch.object(provider, '_get_firecrawl_client', return_value=Client()), \
         patch.object(provider, 'check_website_access', side_effect=[None, blocked]) as policy, \
         patch.object(provider, 'is_safe_url', return_value=True) as safe_url:
        result = asyncio.run(provider._scrape_one(requested, ['markdown', 'html'], None))
    safe_url.assert_called_once_with(final)
    assert [call.args[0] for call in policy.call_args_list] == [requested, final]
    assert result['url'] == final and result['error'] == 'Blocked by policy'
    assert result['content'] == result['raw_content'] == ''
    assert 'html' not in result
