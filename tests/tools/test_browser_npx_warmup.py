"""Retired floating npx cache warmup must never spawn downloaded code."""
from unittest.mock import patch

from tools.browser_tool_install import warm_agent_browser_npx_cache


def test_retired_warmup_never_spawns_even_with_npx_available():
    with patch("tools.browser_tool_install._resolve_npx_bin", return_value="/usr/bin/npx"), \
         patch("subprocess.Popen") as spawn:
        assert warm_agent_browser_npx_cache() is False
        spawn.assert_not_called()
