"""One browser payload serves both headed and headless callers."""
from pathlib import Path

import pytest

from pm.lock import Facts
from pm.packages import Chromium
from pm.defaults import default_package_names
from pm.registry import walk
from scripts.bundles.native import _bundle_package_names


def test_browser_default_and_bundle_ship_full_chromium_only():
    closure = {package.name for package in walk(["chromium"])}
    bundled = set(_bundle_package_names())
    assert "chromium" in set(default_package_names()) & bundled
    assert "chromium-headless-shell" not in closure | bundled


@pytest.mark.parametrize(("target", "version", "relative", "entry_name"), [
    ("linux-x64", "157.0.8103.38", "chrome-linux64/chrome", "chrome-for-testing-157.0.8103.38"),
    ("linux-arm64", "157.0.8103.38", "chrome-linux-arm64/chrome", "chrome-for-testing-157.0.8103.38"),
    ("linux-arm64", "1234+145.0.0.0", "chrome-linux/chrome", "chromium-1234"),
    (
        "darwin-arm64", "157.0.8103.38",
        "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "chrome-for-testing-157.0.8103.38",
    ),
    ("win32-x64", "157.0.8103.38", "chrome-win64/chrome.exe", "chrome-for-testing-157.0.8103.38"),
    ("win32-arm64", "157.0.8103.38", "chrome-win64/chrome.exe", "chrome-for-testing-157.0.8103.38"),
])
def test_chromium_binary_and_env_survive_store_relocation(tmp_path, target, version, relative, entry_name):
    package = Chromium()
    store = tmp_path / "store"
    entry = store / package.store_entry(version, target)
    assert entry.name == entry_name
    executable = entry / relative
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"browser-fixture")
    executable.chmod(0o755)
    assert package.binary(entry, target) == executable
    facts = Facts(store / "facts.json")
    facts.record("chromium", version, entry.name, package.env(entry, target), store)
    moved = tmp_path / "relocated"
    store.rename(moved)
    env = Facts(moved / "facts.json").env_for("chromium", moved)
    assert package.binary(moved / entry.name, target) == moved / entry.name / relative
    assert env == {"PLAYWRIGHT_BROWSERS_PATH": str(moved)}
