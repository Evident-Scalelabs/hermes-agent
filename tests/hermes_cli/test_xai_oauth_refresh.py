from __future__ import annotations

import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from hermes_cli import auth


def test_usable_credentials_do_not_wait_for_another_refresh_transaction(tmp_path, monkeypatch):
    """A factor's healthy snapshot read must not time out behind a slow sibling refresh."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    auth._save_xai_oauth_tokens({"access_token": "usable-access", "refresh_token": "refresh"})
    completed = Event()

    def resolve():
        result = auth.resolve_xai_oauth_runtime_credentials(refresh_if_expiring=False)
        completed.set()
        return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        with auth._auth_store_lock():
            future = pool.submit(resolve)
            completed_while_refreshing = completed.wait(3)
        result = future.result(timeout=5)
    assert completed_while_refreshing, "read-only resolution waited on the refresh writer"
    assert result["api_key"] == "usable-access"
    assert json.loads((tmp_path / "auth.json").read_text())["providers"]["xai-oauth"]["tokens"]["refresh_token"] == "refresh"


def _jwt_with_exp(exp: int) -> str:
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode())
        .decode()
        .rstrip("=")
    )
    return f"{header}.{payload}.sig"




def test_xai_oauth_token_expiring_uses_one_hour_skew() -> None:
    token = _jwt_with_exp(int(time.time()) + 30 * 60)

    assert auth._xai_access_token_is_expiring(
        token,
        auth.XAI_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
    )


def test_xai_proactive_refresh_skew_short_lived_token() -> None:
    token = _jwt_with_exp(int(time.time()) + 15 * 60)
    skew = auth._xai_proactive_refresh_skew_seconds(token)

    assert skew == 120
    assert not auth._xai_access_token_is_expiring(token, skew)


