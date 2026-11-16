"""One browser payload serves both headed and headless callers."""
from pathlib import Path

import pytest

from pm.lock import Facts, Lockfile
from pm.packages import Chromium
from pm.defaults import default_package_names
from pm.paths import lockfile_path
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


def test_locked_chromium_is_patched_chrome_for_testing():
    """The downloader and the lock agree, every target uses the
    Chrome-for-Testing build (linux-arm64 included), and that build is at
    least 156.0.8078.73."""
    package = Chromium()
    lock = Lockfile(lockfile_path())
    version = lock.version(package.name)
    assert version is not None
    chrome = tuple(int(part) for part in (version.partition("+")[2] or version).split("."))
    assert chrome >= (156, 0, 8078, 73)
    for target in ("linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64", "win32-x64", "win32-arm64"):
        url = lock.artifacts(package.name, target)[0]["url"]
        assert url == package.fetch_url(version, target)
        assert "/builds/cft/" in url


@pytest.mark.parametrize("version", ["157.0.8103.38", "1248+157.0.8103.38"])
def test_chromium_version_forms_download_the_same_cft_build(version):
    assert Chromium().fetch_url(version, "linux-arm64") == (
        "https://cdn.playwright.dev/builds/cft/157.0.8103.38/linux-arm64/chrome-linux-arm64.zip"
    )
