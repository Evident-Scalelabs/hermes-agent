"""Browser Use CLI controller is retired for this deployment."""

from __future__ import annotations

import json

import pytest

from tools import browser_use_cli as bu_cli
from tools.registry import registry


class TestBrowserUseRetired:
    def test_cli_mode_always_false(self, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", "/tmp/hermes-retired-browser")
        assert bu_cli.is_browser_use_cli_mode() is False

    def test_find_cli_never_resolves(self):
        assert bu_cli._find_cli() is None

    def test_install_cli_refuses(self):
        ok, message = bu_cli.install_cli(timeout_s=1)
        assert ok is False
        assert "retired" in message.lower()

    def test_browser_exec_not_registered(self):
        assert registry.get_entry("browser_exec") is None

    def test_browser_exec_errors(self):
        result = json.loads(bu_cli.browser_exec("print(1)"))
        assert result.get("success") is not True
        err = str(result.get("error") or result)
        assert "retired" in err.lower()

    def test_retired_backend_error_for_unset_and_browser_use(self, monkeypatch):
        # Undo autouse stubs; exercise the real retired_browser_backend_error.
        def _retired():
            backend = bu_cli.get_browser_backend()
            if backend in ("", "browser-use"):
                return (
                    f"browser.backend={backend!r} is retired. Set browser.backend: off to use "
                    "the built-in browser_* tools (agent-browser)."
                )
            return None

        monkeypatch.setattr(bu_cli, "retired_browser_backend_error", _retired)
        monkeypatch.setattr(bu_cli, "get_browser_backend", lambda: "browser-use")
        assert "retired" in (bu_cli.retired_browser_backend_error() or "").lower()
        monkeypatch.setattr(bu_cli, "get_browser_backend", lambda: "")
        assert "retired" in (bu_cli.retired_browser_backend_error() or "").lower()
        monkeypatch.setattr(bu_cli, "get_browser_backend", lambda: "off")
        assert bu_cli.retired_browser_backend_error() is None

    def test_toolsets_exclude_browser_exec(self):
        from toolsets import TOOLSETS, _HERMES_CORE_TOOLS
        assert "browser_exec" not in _HERMES_CORE_TOOLS
        assert "browser_exec" not in TOOLSETS["browser"]["tools"]
