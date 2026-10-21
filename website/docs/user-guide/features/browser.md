---
title: Browser Automation
description: Control browsers with multiple providers, local Chromium-family browsers via CDP, or cloud browsers for web interaction, form filling, scraping, and more.
sidebar_label: Browser
sidebar_position: 5
---

# Browser Automation

This Evident fork uses the native `browser_*` tools, driven by `agent-browser`, with these browser sources:

- **Browserbase cloud mode** via [Browserbase](https://browserbase.com) as an alternative cloud browser provider with anti-bot tooling
- **Firecrawl cloud mode** via [Firecrawl](https://firecrawl.dev) for cloud browsers with built-in scraping
- **Lightpanda local engine** via [Lightpanda](https://lightpanda.io) for text-focused browser automation, with Chromium fallback for graphical operations
- **Local Chromium-family CDP** — connect browser tools to your own Chrome, Brave, Chromium, or Edge instance using `/browser connect`
- **Local browser mode** via the `agent-browser` CLI and a local Chromium installation

In all modes, the agent can navigate websites, interact with page elements, fill forms, and extract information.

## Overview

Pages are represented as **accessibility trees** (text-based snapshots), making them ideal for LLM agents. Interactive elements get ref IDs (like `@e1`, `@e2`) that the agent uses for clicking and typing.

Key capabilities:

- **Cloud execution** — Browserbase or Firecrawl — no local browser needed
- **Local Chromium-family integration** — attach to your running Chrome, Brave, Chromium, or Edge browser via CDP for hands-on browsing
- **Session isolation** — each task gets its own browser session
- **Automatic cleanup** — inactive sessions are closed after a timeout
- **Vision analysis** — screenshot + AI analysis for visual understanding

## Setup

### Native browser controller

Set the controller explicitly in `~/.hermes/config.yaml`:

```yaml
browser:
  backend: "off"
  cloud_provider: local
```

`backend: "off"` selects the native tools; it does not disable browser automation. `cloud_provider: local` selects packaged Chromium. To use a supported cloud browser, keep `backend: "off"` and change `cloud_provider` to `browserbase` or `firecrawl`.

Browser Use CLI/cloud, `browser_exec`, Nous browser hosting, and Camofox are retired in this fork. Existing selections of those routes return configuration guidance; no Browser Use installation or controller fallback is attempted.

Legacy `browser.camofox.rewrite_loopback_urls` and `browser.camofox.loopback_host_alias` settings are inactive while the Camofox controller is retired.

Each task owns its native browser session. CDP tasks also bind their own tab, so concurrent tasks do not share the same tab or daemon. Cleanup closes owned resources after inactivity or shutdown. To use an existing browser or saved logins, see [CDP connections](#local-chromium-family-browser-via-cdp-browser-connect) and [real-profile browsing](#real-profile-browsing-use-your-own-logins).

### Browserbase cloud mode

To use Browserbase-managed cloud browsers, add:

```bash
# Add to ~/.hermes/.env
BROWSERBASE_API_KEY=***
BROWSERBASE_PROJECT_ID=your-project-id-here
```

Get your credentials at [browserbase.com](https://browserbase.com).

:::note Selecting the provider
The `.env` keys above supply **credentials only**. The active cloud browser is chosen by the `browser.cloud_provider` selection written by `hermes tools` → Browser Automation (`local`, `browserbase`, `firecrawl`, or an installed browser-provider plugin). Once a selection exists, adding or removing a key does not switch providers — and a selected provider with a missing key errors with guidance to run `hermes tools` instead of silently rerouting. Never-configured setups can autodetect Browserbase from its credentials; set `cloud_provider: local` to keep local browsing explicit.
:::

### Firecrawl cloud mode

To use Firecrawl as your cloud browser provider, add:

```bash
# Add to ~/.hermes/.env
FIRECRAWL_API_KEY=fc-***
```

Get your API key at [firecrawl.dev](https://firecrawl.dev). Then select Firecrawl as your browser provider:

```bash
hermes setup tools
# → Browser Automation → Firecrawl
```

Optional settings:

```bash
# Self-hosted Firecrawl instance (default: https://api.firecrawl.dev)
FIRECRAWL_API_URL=http://localhost:3002

# Session TTL in seconds (default: 300)
FIRECRAWL_BROWSER_TTL=600
```

### Hybrid routing: cloud for public URLs, local for LAN/localhost

When a cloud provider is configured, Hermes auto-spawns a **local Chromium sidecar**
for URLs that resolve to a private/loopback/LAN address (`localhost`, `127.0.0.1`,
`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`, `*.local`, `*.lan`, `*.internal`,
IPv6 loopback `::1`, link-local `169.254.x.x`). Public URLs continue to use the
cloud provider in the same conversation.

This solves the common "I'm developing locally but using Browserbase" workflow —
the agent can screenshot your dashboard at `http://localhost:3000` AND scrape
`https://github.com` without you switching providers or disabling the SSRF guard.
The cloud provider never sees the private URL.

The feature is **on by default**. To disable it (all URLs go to the configured
cloud provider, as before):

```yaml
# ~/.hermes/config.yaml
browser:
  cloud_provider: browserbase
  auto_local_for_private_urls: false
```

With auto-routing disabled, private URLs are rejected with
`"Blocked: URL targets a private or internal address"` unless you also set
`browser.allow_private_urls: true` (which lets the cloud provider attempt them —
usually won't work since Browserbase etc. can't reach your LAN).

Requirements: the local sidecar uses the same `agent-browser` CLI as pure local
mode, so you need it installed (`hermes setup tools → Browser Automation`
auto-installs it). Post-navigation redirects from a public URL onto a private
address are still blocked (you can't use a redirect-to-internal trick to reach
your LAN through the public path).

### Real profile browsing (use your own logins)

By default, local browsing runs in a clean, throwaway profile — the agent is
logged into nothing. Turn on **real profile browsing** to let the agent browse
as *you*, with your existing logins and cookies:

```yaml
# ~/.hermes/config.yaml
browser:
  use_real_profile: true
```

When enabled, Hermes copies your default browser's **active** profile — the one
you actually browse (`Local State → profile.last_used`), with its cookies, saved
logins, and preferences — into a managed snapshot under
`~/.hermes/browser-profile/<browser>/`, then launches your **real browser
binary** on that snapshot and attaches its browsing engine to it. Launching the
real binary (instead of a bundled Chromium with mock-keychain switches) is what
keeps OS-encrypted cookies decryptable — on macOS, Chrome cookies are encrypted
through the Keychain, and a mock-keychain launch would silently drop every one
of them, opening signed out. Your live browser profile is **never opened
directly**: the
snapshot is a separate directory, so it doesn't fight your running browser for
the profile lock and it sidesteps Chrome 136+'s block on remote-debugging the
default profile directory. The auth files (cookies/logins/preferences) are
re-synced from your real profile whenever a fresh session is launched, so logins
you do in your own browser show up in the agent's session. Only the active
profile is copied — other Chrome profiles are never snapshotted.

The snapshot browser runs **headless** — it drives your profile in the
background with no visible window and never steals focus, so you can keep
working while the agent tweets, fills forms, or scrapes on your behalf.
(Headless here uses Chrome's *new* headless mode, which reads your normal
cookie store, so your logins still load.) If you'd rather watch it work, the
same [headed-mode](#headed-mode-visible-browser-window) toggle applies —
`browser.headed: true` (or `AGENT_BROWSER_HEADED=1`) opens a visible window for
real-profile browsing too. On a display-less host (servers, CI) it always runs
headless regardless.

If your browser has several profiles (say a work profile and a personal one)
and you don't want "whichever profile you touched last" deciding the agent's
identity, pin the snapshot source explicitly:

```yaml
# ~/.hermes/config.yaml
browser:
  use_real_profile: true
  real_profile_pin: "Profile 2"   # directory name under the browser's user-data dir
```

A pin naming a profile directory that doesn't exist never silently falls back to
the last-used profile: the agent gets a fresh browser without your logins and a
message naming the bad pin.

When you turn the toggle back off, Hermes deletes the snapshot store
(`~/.hermes/browser-profile/`) on the next browser use, so the copied
credentials don't linger after you revoke consent.

:::note When your profile can't be copied, the browser still works
Real-profile browsing never takes the browser away. If Hermes can't copy your
profile, the agent gets a fresh browser **without your logins** for that session,
and its first browser result says why (`real_profile_unavailable`), so it can tell
you instead of acting as if it were signed in. That happens when:

- **Windows, first use only:** a running Chrome/Edge/Brave holds its cookie
  database with an exclusive (deny-all) lock, so the first copy needs the browser
  **fully quit**, including any background/tray instance (Chrome's "continue
  running background apps when closed" keeps a `chrome.exe` alive after you close
  the window). After one successful copy, a later launch with the browser open
  reuses that copy instead: your logins are as of the last copy, and they refresh
  the next time Hermes starts its browser while yours is closed.
- **Your default browser isn't a supported Chromium** (Firefox, a Beta/Dev/Canary
  channel), or the pinned profile doesn't exist.
- **The cookie database is unreadable or corrupt**: the message names it and the
  SQLite error.

On macOS and Linux a running Chrome holds `Login Data`, `Login Data For Account`
and `Web Data` (saved passwords and autofill) with a write lock, but `Cookies`
still copies, and cookies are what keep you signed in to sites. Hermes copies the
cookies and skips the locked password/autofill files, so you can keep your browser
open. Each database is copied through SQLite's online backup (never a raw file
copy, which could lose recent logins).

Set `browser.real_profile_autoclose: true` to let Hermes **offer to close the
browser for you** when it's holding the profile lock (the Windows case). Even with
this on, Hermes never closes it automatically: the agent asks you first, and only on
your approval runs `hermes browser close-profile` (terminates the browser process
tree bound to that profile, losing unsaved tabs). A new browser session then picks
up your profile.
:::

- **Supported browsers:** Chrome, Edge, Brave, Brave Origin, Chromium (whichever is your OS
  default). A non-Chromium default (e.g. Firefox) fails closed with a clear
  message rather than guessing.
- **Requires local browser mode.** Set `browser.cloud_provider: local` to
  use the snapshot automatically once the toggle is on. A configured cloud
  provider or `/browser connect` endpoint takes precedence. Hybrid private-URL
  sidecars use a clean profile rather than your copied logins.
- **Security framing:** this is a consent-gated convenience, not an isolation
  boundary. A page the agent visits runs with your real logins, so only enable
  it when you want the agent acting as you. Off by default.
- **Desktop:** toggle it in **Capabilities → Tools → Browser → Use My Real
  Browser Profile** (the switch sits above the backend options), or in
  Settings → Config under the `browser` section.

#### Scheduled and unattended runs

A real-profile session lets a `cronjob` drive a site you're already signed into.
The snapshot runs headless by default, and the auth files (`Cookies`,
`Login Data`, …) are re-synced from your real profile on every fresh session —
an already-open session is reused as-is, so the sync happens when a new one is
launched. Without saved vault credentials, an expired session on that site
surfaces as a login page that the unattended tick reports rather than hanging on.

Three things to set up before scheduling one:

- **Turn the toggle on.** `browser.use_real_profile` defaults to `false`, and
  without it the job gets a clean, unauthenticated profile — see above.
- **Give the job the browser toolset:**
  `cronjob(action="create", enabled_toolsets=["browser", ...], ...)` — a per-job
  list wins over the cron-platform config
  ([details](./cron.md#toolsets-available-to-cron-jobs)).
- **Assume nothing can be prompted for.** A cron, webhook, API or
  `hermes chat -q` session has nobody to answer a prompt, so a site that is not
  usable on the synced cookies alone — a login form, a fresh 2FA challenge —
  needs its credentials saved ahead of time, authenticator key included. That is
  the [credential vault's](./credential-vault.md#headless-sessions) job, and it
  is what carries a run after your own session has expired.

**Windows prerequisite:** the browser has to be fully quit for the first snapshot.
After that, a tick that runs while it is open reuses the last snapshot (logins as of
that copy); with no snapshot yet, the tick runs on a fresh, signed-out browser. Hermes never closes it without asking you first
(see the note above).

The bundled `product-price-monitor` skill is a worked example of the recurring
shape — a JSON watch contract written during setup, then one scheduled tick that
re-reads it, compares, and alerts on change — though it covers the scheduling
half, not logins.

### Lightpanda local engine

[Lightpanda](https://lightpanda.io) is an open-source headless browser written from scratch. It starts instantly, runs 9x faster and uses 16x less memory than Chrome, which matters for agents that live on small VMs for long stretches.

Lightpanda is a **local engine** (a browser source, like "Local Browser"), not a cloud provider. Install the binary and put it on your `PATH` (see the [Lightpanda installation guide](https://lightpanda.io/docs/run-locally/installation/one-liner)), then pick **Lightpanda** in `hermes tools` → Browser Automation, or set:

```yaml
# Add to ~/.hermes/config.yaml
browser:
  cloud_provider: local
  engine: lightpanda
```

Or via environment variable:

```bash
AGENT_BROWSER_ENGINE=lightpanda
```

Hermes drives Lightpanda through `agent-browser --engine lightpanda` over CDP. It handles supported text and interaction commands; graphical operations such as screenshots and `browser_vision` use Chromium. Other failed operations can retry in Chromium with a fallback warning. A command reported as `outcome_unknown` is returned without replaying it in another engine.

**When the engine is ignored.** A configured cloud provider, a `browser.cdp_url` / `/browser connect` override, or real-profile browsing takes precedence over `browser.engine`. Picking Lightpanda in `hermes tools` writes `cloud_provider: local`; `/browser status` and `hermes doctor` report when another source overrides the engine.

### Local Chromium-family browser via CDP (`/browser connect`)

Instead of a cloud provider, you can attach Hermes browser tools to your own running Chrome, Brave, Chromium, or Edge instance via the Chrome DevTools Protocol (CDP). This is useful when you want to see what the agent is doing in real-time, interact with pages that require your own cookies/sessions, or avoid cloud browser costs.

:::note
`/browser connect` is an **interactive-CLI slash command** — it is not dispatched by the gateway. If you try to run it inside a WebUI, Telegram, Discord, or other gateway chat, the message will be sent to the agent as plain text and the command will not execute. Start Hermes from the terminal (`hermes` or `hermes chat`) and issue `/browser connect` there.
:::

In the CLI, use:

```
/browser connect                 # Auto-launch/connect to a local Chromium-family browser at http://127.0.0.1:9222
/browser connect ws://host:port  # Connect to a specific CDP endpoint
/browser status                  # Check current connection
/browser disconnect              # Detach and return to cloud/local mode
```

If a browser isn't already running with remote debugging, Hermes will attempt to auto-launch a supported Chromium-family browser with `--remote-debugging-port=9222`. Detection includes Brave, Brave Origin/Nightly, Google Chrome, Chromium, and Microsoft Edge, with common Linux install paths and binary names such as `brave-origin`, `brave-origin-nightly`, `/opt/brave.com/brave-origin/brave-origin`, `/opt/brave.com/brave-origin-nightly/brave-origin`, `/opt/brave-bin/brave`, and `/snap/bin/brave`.

:::tip
To start a Chromium-family browser manually with CDP enabled, use a dedicated user-data-dir so the debug port actually comes up even if the browser is already running with your normal profile:

```bash
# Linux — Brave
brave-browser \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.hermes/chrome-debug \
  --no-first-run \
  --no-default-browser-check &

# Linux — Google Chrome
google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.hermes/chrome-debug \
  --no-first-run \
  --no-default-browser-check &

# macOS — Brave
"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.hermes/chrome-debug" \
  --no-first-run \
  --no-default-browser-check &

# macOS — Google Chrome
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.hermes/chrome-debug" \
  --no-first-run \
  --no-default-browser-check &
```

Then launch the Hermes CLI and run `/browser connect`.

**Why `--user-data-dir`?** Without it, launching a Chromium-family browser while a regular instance is already running typically opens a new window on the existing process — and that existing process was not started with `--remote-debugging-port`, so port 9222 never opens. A dedicated user-data-dir forces a fresh browser process where the debug port actually listens. `--no-first-run --no-default-browser-check` skips the first-launch wizard for the fresh profile.

**Chrome 136+ makes the dedicated profile mandatory.** Two separate mechanisms are in play, and neither applies once you pass a non-default `--user-data-dir`. First, since [Chrome 136](https://developer.chrome.com/blog/remote-debugging-port) `--remote-debugging-port` and `--remote-debugging-pipe` "will no longer be respected if attempting to debug the default Chrome data directory" — the flag is silently ignored, no dialog, and `/browser connect` (or `curl http://127.0.0.1:9222/json/version`) gets connection refused even from a cold start. Second, [Chrome 144+](https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session) adds an opt-in *approval* flow for debugging your real profile: you enable it under `chrome://inspect/#remote-debugging`, and Chrome then shows an **"Allow remote debugging?"** dialog for **every incoming connection** (not once per launch), with nothing listening until you press **Allow**. If you see that dialog, you are on the approval path, not the flag path. The fix is exactly the commands above: point `--user-data-dir` somewhere other than your default profile directory (e.g. `$HOME/.hermes/chrome-debug`), which needs neither the toggle nor the dialog. This applies to Chrome, Chromium, Edge, and Brave builds that have picked up the change.

A dedicated profile starts out signed out of everything. If you want the agent to browse with your existing logins *and* no approval dialog, use [`browser.use_real_profile`](#real-profile-browsing-use-your-own-logins) instead: it snapshots your active profile into a copy and drives that, which is a non-default user-data-dir and so never triggers either mechanism.
:::

When connected via CDP, all browser tools (`browser_navigate`, `browser_click`, etc.) operate on your live browser instance instead of spinning up a cloud session.

### WSL2 + Windows Chrome: prefer MCP over `/browser connect`

If Hermes runs inside WSL2 but the Chrome window you want to control runs on the Windows host, `/browser connect` is often not the best path.

Why:

- `/browser connect` expects Hermes itself to reach a usable CDP endpoint
- modern Chrome live-debugging sessions often expose a host-local endpoint that is not directly reachable from WSL the same way a classic `9222` port is
- even when Windows Chrome is debuggable, the cleanest integration is often to let a Windows-side browser MCP server attach to Chrome and let Hermes talk to that MCP server

For that setup, prefer `chrome-devtools-mcp` through Hermes MCP support.

See the MCP guide for the practical setup:

- [Use MCP with Hermes](../../guides/use-mcp-with-hermes.md#wsl2-bridge-hermes-in-wsl-to-windows-chrome)

### Local browser mode

If you do **not** set any cloud credentials and don't use `/browser connect`, Hermes can still use the browser tools through a local Chromium install driven by `agent-browser`.

### Optional Environment Variables

```bash
# Residential proxies for better CAPTCHA solving (default: "true")
BROWSERBASE_PROXIES=true

# Advanced stealth with custom Chromium — requires Scale Plan (default: "false")
BROWSERBASE_ADVANCED_STEALTH=false

# Session reconnection after disconnects — requires paid plan (default: "true")
BROWSERBASE_KEEP_ALIVE=true

# Custom session timeout in seconds (max 21600 = 6 hours) (default: project default)
# Examples: 600 (10min), 1800 (30min), 21600 (6h max)
BROWSERBASE_SESSION_TIMEOUT=1800

# Inactivity timeout before auto-cleanup in seconds (default: 120)
BROWSER_INACTIVITY_TIMEOUT=120

# Local browser engine. Equivalent to browser.engine in config.yaml;
# passed to agent-browser as --engine.
#   auto       — Chrome (default)
#   lightpanda — Lightpanda
#   chrome     — force Chrome explicitly
AGENT_BROWSER_ENGINE=auto

# Extra Chromium launch flags (comma- or newline-separated). Hermes auto-injects
# `--no-sandbox,--disable-dev-shm-usage` when it detects root or AppArmor-restricted
# unprivileged user namespaces (Ubuntu 23.10+, DGX Spark, many container images),
# so most users don't need to set this. Set it manually only if you need a flag
# Hermes doesn't add automatically; setting it disables the auto-injection.
AGENT_BROWSER_ARGS=--no-sandbox
```

### Install agent-browser CLI

The installers and `hermes update` install `agent-browser` and its pinned
Chromium through Hermes's package manager by default. If you installed with
`--skip-browser` / `-SkipBrowser`, or the download failed, install them with:

```bash
hermes pm install agent-browser
```

This also undoes an earlier `--skip-browser` choice, so updates keep the
browser tools current. An `agent-browser` already on your `PATH` also works.
On Linux, Chromium may also need system libraries
(`npx playwright install-deps chromium`). On Android/Termux, run
`npm install -g agent-browser && agent-browser install` instead.

:::info
The `browser` toolset must be included in your config's `toolsets` list or enabled via `hermes config set toolsets '["hermes-cli", "browser"]'`.
:::

## Available Tools

### `browser_navigate`

Navigate to a URL. Call it before interacting with page elements; it initializes the task's configured local or cloud browser session.

```
Navigate to https://github.com/NousResearch
```

:::tip
For simple information retrieval, prefer `web_search` or `web_extract` — they are faster and cheaper. Use browser tools when you need to **interact** with a page (click buttons, fill forms, handle dynamic content).
:::

### `browser_snapshot`

Get a text-based snapshot of the current page's accessibility tree. Returns interactive elements with ref IDs like `@e1`, `@e2` for use with `browser_click` and `browser_type`.

- **`full=false`** (default): Compact view showing only interactive elements
- **`full=true`**: Complete page content

Snapshots larger than `browser.snapshot_threshold` (default 15,000 characters — the same per-page budget as `web_extract`) are automatically truncated at line boundaries; no LLM summarization is involved. When that happens, the complete snapshot is saved to `~/.hermes/cache/web/` and the tool output includes the file path plus a ready-to-use `read_file` call, so the agent can page through the full accessibility tree — including element refs beyond the cut — without re-snapshotting.

Increase the threshold for long pages where more source content should reach the agent inline:

```yaml
# ~/.hermes/config.yaml
browser:
  snapshot_threshold: 30000
```

You can also run `hermes config set browser.snapshot_threshold 30000`. The setting applies to both explicit `browser_snapshot` calls and the automatic snapshot returned after navigation (minimum 1000). Restart the current Hermes session after changing it so the browser config cache reloads.

### `browser_click`

Click an element identified by its ref ID from the snapshot.

```
Click @e5 to press the "Sign In" button
```

### `browser_type`

Type text into an input field. Clears the field first, then types the new text.

```
Type "hermes agent" into the search field @e3
```

### `browser_scroll`

Scroll the page up or down to reveal more content.

```
Scroll down to see more results
```

### `browser_press`

Press a keyboard key. Useful for submitting forms or navigation.

```
Press Enter to submit the form
```

Supported keys: `Enter`, `Tab`, `Escape`, `ArrowDown`, `ArrowUp`, and more.

### `browser_back`

Navigate back to the previous page in browser history.

### `browser_get_images`

List all images on the current page with their URLs and alt text. Useful for finding images to analyze.

### `browser_vision`

Take a screenshot and analyze it with vision AI. Use this when text snapshots don't capture important visual information — especially useful for CAPTCHAs, complex layouts, or visual verification challenges.

The screenshot is saved persistently and the file path is returned alongside the AI analysis. On messaging platforms (Telegram, Discord, Slack, WhatsApp), you can ask the agent to share the screenshot — it will be sent as a native photo attachment via the `MEDIA:` mechanism.

```
What does the chart on this page show?
```

Screenshots are stored in `~/.hermes/cache/screenshots/` and automatically cleaned up after 24 hours.

### `browser_console`

Get browser console output (log/warn/error messages) and uncaught JavaScript exceptions from the current page. Essential for detecting silent JS errors that don't appear in the accessibility tree.

```
Check the browser console for any JavaScript errors
```

Use `clear=True` to clear the console after reading, so subsequent calls only show new messages.

`browser_console` also evaluates JavaScript when called with an `expression` argument — same shape as DevTools console, the result comes back parsed (JSON-serialized objects become dicts; primitive values stay primitive).

```
browser_console(expression="document.querySelector('h1').textContent")
browser_console(expression="JSON.stringify(performance.timing)")
```

When a CDP supervisor is active for the current session (typical for any session that's run `browser_navigate` against a CDP-capable backend), evaluation runs over the supervisor's persistent WebSocket — no subprocess startup cost. Falls through to the standard agent-browser CLI path otherwise. Behaviour is identical either way; only latency changes.

Evaluation is unrestricted by default — the agent can use `fetch`, read storage, query form values, and run any DOM extraction. Requests targeting private/internal addresses are still blocked on non-local backends (the SSRF guard is independent of this setting). If you browse hostile pages with a logged-in profile and want a strict denylist over sensitive JS primitives (cookies, storage, clipboard, network calls, form values), opt in with `browser.restrict_evaluate: true` in `config.yaml`. Note the denylist matches primitive *names*, so it also blocks legitimate expressions that merely contain words like `fetch` or `cookie`.

### `browser_cdp`

Raw Chrome DevTools Protocol passthrough — the escape hatch for browser operations not covered by the other tools. Use for native dialog handling, iframe-scoped evaluation, cookie/network control, or any CDP verb the agent needs.

**Only available when a CDP endpoint is reachable at session start** — meaning `/browser connect` has attached to a running Chrome, Brave, Chromium, or Edge browser, or `browser.cdp_url` is set in `config.yaml`. The default local agent-browser mode and cloud providers (Browserbase, Firecrawl) do not currently expose CDP to this tool — cloud providers have per-session CDP URLs but live-session routing is a follow-up.

**CDP method reference:** https://chromedevtools.github.io/devtools-protocol/ — the agent can `web_extract` a specific method's page to look up parameters and return shape.

Common patterns:

```
# List tabs (browser-level, no target_id)
browser_cdp(method="Target.getTargets")

# Handle a native JS dialog on a tab
browser_cdp(method="Page.handleJavaScriptDialog",
            params={"accept": true, "promptText": ""},
            target_id="<tabId>")

# Evaluate JS in a specific tab
browser_cdp(method="Runtime.evaluate",
            params={"expression": "document.title", "returnByValue": true},
            target_id="<tabId>")

# Get all cookies
browser_cdp(method="Network.getAllCookies")
```

Browser-level methods (`Target.*`, `Browser.*`, `Storage.*`) omit `target_id`. Page-level methods (`Page.*`, `Runtime.*`, `DOM.*`, `Emulation.*`) require a `target_id` from `Target.getTargets`. Each stateless call is independent — sessions do not persist between calls.

**Cross-origin iframes:** pass `frame_id` (from `browser_snapshot.frame_tree.children[]` where `is_oopif=true`) to route the CDP call through the supervisor's live session for that iframe. This is how `Runtime.evaluate` inside a cross-origin iframe works on Browserbase, where stateless CDP connections would hit signed-URL expiry. Example:

```
browser_cdp(
  method="Runtime.evaluate",
  params={"expression": "document.title", "returnByValue": True},
  frame_id="<frame_id from browser_snapshot>",
)
```

Same-origin iframes don't need `frame_id` — use `document.querySelector('iframe').contentDocument` from a top-level `Runtime.evaluate` instead.

### `browser_dialog`

Responds to a native JS dialog (`alert` / `confirm` / `prompt` / `beforeunload`). Before this tool existed, dialogs would silently block the page's JavaScript thread and subsequent `browser_*` calls would hang or throw; now the agent sees pending dialogs in `browser_snapshot` output and responds explicitly.

**Workflow:**
1. Call `browser_snapshot`. If a dialog is blocking the page, it shows up as `pending_dialogs: [{"id": "d-1", "type": "alert", "message": "..."}]`.
2. Call `browser_dialog(action="accept")` or `browser_dialog(action="dismiss")`. For `prompt()` dialogs, pass `prompt_text="..."` to supply the response.
3. Re-snapshot — `pending_dialogs` is empty; the page's JS thread has resumed.

**Detection happens automatically** via a persistent CDP supervisor — one WebSocket per task that subscribes to Page/Runtime/Target events. The supervisor also populates a `frame_tree` field in the snapshot so the agent can see the iframe structure of the current page, including cross-origin (OOPIF) iframes.

**Availability matrix:**

| Backend | Detection via `pending_dialogs` | Response (`browser_dialog` tool) |
|---|---|---|
| Local Chrome via `/browser connect` or `browser.cdp_url` | ✓ | ✓ full workflow |
| Browserbase | ✓ | ✓ full workflow (via injected XHR bridge) |
| Default local agent-browser | ✗ | ✗ (no CDP endpoint) |

**How it works on Browserbase.** Browserbase's CDP proxy auto-dismisses real native dialogs server-side within ~10ms, so we can't use `Page.handleJavaScriptDialog`. The supervisor injects a small script via `Page.addScriptToEvaluateOnNewDocument` that overrides `window.alert`/`confirm`/`prompt` with a synchronous XHR. We intercept those XHRs via `Fetch.enable` — the page's JS thread stays blocked on the XHR until we call `Fetch.fulfillRequest` with the agent's response. `prompt()` return values round-trip back into page JS unchanged.

**Dialog policy** is configured in `config.yaml` under `browser.dialog_policy`:

| Policy | Behavior |
|--------|----------|
| `must_respond` (default) | Capture, surface in snapshot, wait for explicit `browser_dialog()` call. Safety auto-dismiss after `browser.dialog_timeout_s` (default 300s) so a buggy agent can't stall forever. |
| `auto_dismiss` | Capture, dismiss immediately. Agent still sees the dialog in `browser_state` history but doesn't have to act. |
| `auto_accept` | Capture, accept immediately. Useful when navigating pages with aggressive `beforeunload` prompts. |

**Frame tree** inside `browser_snapshot.frame_tree` is capped to 30 frames and OOPIF depth 2 to keep payloads bounded on ad-heavy pages. A `truncated: true` flag surfaces when limits were hit; agents needing the full tree can use `browser_cdp` with `Page.getFrameTree`.

## Practical Examples

### Filling Out a Web Form

```
User: Sign up for an account on example.com with my email john@example.com

Agent workflow:
1. browser_navigate("https://example.com/signup")
2. browser_snapshot()  → sees form fields with refs
3. browser_type(ref="@e3", text="john@example.com")
4. browser_type(ref="@e5", text="SecurePass123")
5. browser_click(ref="@e8")  → clicks "Create Account"
6. browser_snapshot()  → confirms success
```

### Researching Dynamic Content

```
User: What are the top trending repos on GitHub right now?

Agent workflow:
1. browser_navigate("https://github.com/trending")
2. browser_snapshot(full=true)  → reads trending repo list
3. Returns formatted results
```

## Session Recording

Automatically record browser sessions as WebM video files:

```yaml
browser:
  record_sessions: true  # default: false
```

When enabled, recording starts automatically on the first `browser_navigate` and saves to `~/.hermes/browser_recordings/` when the session closes. Works in both local and cloud (Browserbase) modes. Recordings older than 72 hours are automatically cleaned up.

## Headed Mode (Visible Browser Window)

By default, the local browser runs headless. Enable headed mode to get a visible Chromium window you can watch and interact with:

```yaml
browser:
  headed: true  # default: false
```

Or via environment variable: `AGENT_BROWSER_HEADED=1`.

Headed mode does two things:

1. **Launches Chromium with a visible window** (passes `--headed` to agent-browser in local mode).
2. **Keeps the window open between turns.** Normally the browser session is cleaned up after every agent reply; in headed mode the per-turn cleanup is skipped so you can watch the agent work, intervene manually (sign-in challenges, CAPTCHAs), and keep login state warm across the conversation.

Idle sessions are still reaped after `browser.inactivity_timeout` (default 120s of no browser activity), and all sessions are closed on shutdown. Headed mode only affects the local browser — cloud sessions (Browserbase) are unaffected.

## Stealth Features

Browserbase provides automatic stealth capabilities:

| Feature | Default | Notes |
|---------|---------|-------|
| Basic Stealth | Always on | Random fingerprints, viewport randomization, CAPTCHA solving |
| Residential Proxies | On | Routes through residential IPs for better access |
| Advanced Stealth | Off | Custom Chromium build, requires Scale Plan |
| Keep Alive | On | Session reconnection after network hiccups |

:::note
If paid features aren't available on your plan, Hermes automatically falls back — first disabling `keepAlive`, then proxies — so browsing still works on free plans.
:::

## Session Management

- Each task gets an isolated native session; CDP connections also bind a task-owned tab
- Sessions are automatically cleaned up after inactivity (default: 2 minutes)
- A background thread checks every 30 seconds for stale sessions
- Emergency cleanup runs on process exit to prevent orphaned sessions
- Cloud sessions are released through their configured provider; local sessions close their owned browser resources

## Limitations

- **Text-based interaction** — relies on accessibility tree, not pixel coordinates
- **Snapshot size** — large pages are truncated at `browser.snapshot_threshold` (default 15,000 characters, matching `web_extract`; no LLM summarization); the complete snapshot is saved to `~/.hermes/cache/web/` and the output points at it for `read_file` paging
- **Session timeout** — cloud sessions expire based on your provider's plan settings
- **Cost** — cloud sessions consume provider credits; sessions are automatically cleaned up when the conversation ends or after inactivity. Use `/browser connect` for free local browsing.
- **No file downloads** — cannot download files from the browser
