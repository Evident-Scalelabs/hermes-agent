import asyncio
from unittest.mock import patch
from plugins.web.firecrawl import provider
from tools.web_tools_truncate import _trim_results, _truncate_results


def test_firecrawl_preserves_full_page_options_and_evidence():
    seen = {}
    class Client:
        def scrape(self, **kwargs):
            seen.update(kwargs)
            return {'markdown': 'Offer and disclosure', 'html': '<h1>Offer</h1><footer>Disclosure</footer>',
                    'metadata': {'title': 'Offer', 'sourceURL': 'https://example.com/offer', 'statusCode': 200}}
    with patch.object(provider, '_get_firecrawl_client', return_value=Client()), \
         patch.object(provider, 'check_website_access', return_value=None), \
         patch.object(provider, 'is_safe_url', return_value=True), \
         patch('tools.web_tools._load_web_config', return_value={'firecrawl': {'only_main_content': False, 'max_age': 0}}):
        result = asyncio.run(provider._scrape_one('https://example.com/offer', ['markdown', 'html'], None))
    _truncate_results([result], 2000, {'pages_truncated': 0, 'truncation_metrics': []})
    projected = _trim_results([result])[0]
    assert seen['only_main_content'] is False and seen['max_age'] == 0
    assert projected['html'].endswith('<footer>Disclosure</footer>')
    assert projected['metadata']['statusCode'] == 200
    assert projected['provider'] == 'firecrawl'
    assert projected['truncated'] is False
