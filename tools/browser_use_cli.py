"""Retired Browser Use CLI controller (Evident-managed Hermes deployment).

The Browser Use CLI, ``browser_exec`` tool, ``uvx``/``uv tool install`` paths, and
``browser.backend: browser-use`` selection are removed. Built-in ``browser_*`` tools
backed by agent-browser are the only supported controller (``browser.backend: off``).

This module remains importable so transitional callers that only need config reads
(``_read_browser_cfg``) or the retired-mode predicate keep working. It does not
register tools, install packages, or execute Browser Use code.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BACKEND_DISABLED = "off"
_BACKEND_KEY = "browser-use"

RETIRED_MSG = (
    "Browser Use CLI is retired. Set browser.backend: off and use the built-in "
    "browser_* tools (agent-browser). There is no install or uvx fallback."
)
_RETIRED_MSG = RETIRED_MSG  # back-compat alias


def _read_browser_cfg() -> dict:
    """Return the ``browser:`` config section, or {} on any failure."""
    try:
        from hermes_cli.config import cfg_get, read_raw_config
        cfg = cfg_get(read_raw_config(), "browser", default={})
        return cfg if isinstance(cfg, dict) else {}
    except Exception as e:
        logger.debug("Could not read browser config section: %s", e)
        return {}


def get_browser_backend() -> str:
    """Configured browser backend key ("" = unset). YAML 1.1 parses an unquoted
    ``off`` as False — that must mean BACKEND_DISABLED, not "unset"."""
    raw = _read_browser_cfg().get("backend")
    return (BACKEND_DISABLED if raw is False else "") if isinstance(raw, bool) else str(raw or "").strip().lower()


def retired_browser_backend_error() -> Optional[str]:
    """Actionable error when config still selects the retired controller or leaves it unset."""
    browser_cfg = _read_browser_cfg()
    from tools.tool_backend_helpers import normalize_browser_cloud_provider
    from agent.secret_scope import get_secret
    selected = normalize_browser_cloud_provider(browser_cfg.get("cloud_provider"))
    if selected == "camofox" or ("cloud_provider" not in browser_cfg and get_secret("CAMOFOX_URL", "")):
        return "Camofox controller is retired. Select local Chromium or an agent-browser CDP provider explicitly."
    backend = get_browser_backend()
    if backend in ("", _BACKEND_KEY):
        return (
            f"browser.backend={backend!r} is retired. Set browser.backend: off to use "
            "the built-in browser_* tools (agent-browser). Unset defaults no longer "
            "install or select Browser Use."
        )
    return None


def is_legacy_browser_use_cloud_config(browser_cfg: dict) -> bool:
    """Always False: Browser Use cloud CLI mode is retired."""
    return False


def is_browser_use_cli_mode() -> bool:
    """Always False: the Browser Use CLI controller is retired."""
    return False


def default_downgrade_notice() -> Optional[str]:
    """No downgrade notice: Browser Use is not a default."""
    return None


def _find_cli() -> Optional[List[str]]:
    """Never locate Browser Use — install and uvx paths are closed."""
    return None


def install_cli(timeout_s: int = 600) -> Tuple[bool, str]:
    """Refuse to install the retired Browser Use CLI."""
    return False, _RETIRED_MSG


def browser_exec(code: str, session: str = "", timeout_s: int = 120,
                 task_id: Optional[str] = None, local: bool = False) -> str:
    """Retired entrypoint: always returns an error JSON string."""
    from tools.registry import tool_error
    return tool_error(_RETIRED_MSG)


# Intentionally no registry.register("browser_exec", ...).
