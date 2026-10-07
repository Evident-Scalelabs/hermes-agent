"""One repository quota applies to every candidate path in a Hub fetch."""
from unittest.mock import patch

import httpx

from tools.skills_hub_github import GitHubAuth, GitHubSource


def test_exhausted_source_stops_requesting_other_repository_paths():
    source = GitHubSource(GitHubAuth())
    response = httpx.Response(403, headers={
        "X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "5000",
    })
    with patch("tools.skills_hub._skills_hub_http_get", return_value=response) as get:
        first = source._github_get("https://api.github.com/repos/example/skills", max_retries=1)
        assert first is response
        assert source.is_rate_limited
        assert source._github_get("https://api.github.com/repos/example/skills/contents/other") is None
        assert get.call_count == 1


def test_permission_denial_keeps_other_repository_paths_available():
    source = GitHubSource(GitHubAuth())
    responses = [httpx.Response(403, headers={"X-RateLimit-Remaining": "5000"}), httpx.Response(200)]
    with patch("tools.skills_hub._skills_hub_http_get", side_effect=responses) as get:
        source._github_get("https://api.github.com/repos/example/skills", max_retries=1)
        assert not source.is_rate_limited
        assert source._github_get("https://api.github.com/repos/example/other").status_code == 200
        assert get.call_count == 2
