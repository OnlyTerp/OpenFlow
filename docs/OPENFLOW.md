# OpenFlow multi-provider STT

OpenFlow is a local Windows Electron dictation app that routes speech to one selected
provider. The Electron app is the product; the HTTP shim runs invisibly on loopback.

## Providers

| Id | Transport | Local authentication | Notes |
|---|---|---|---|
| `grok` | xAI speech-to-text API | Grok CLI OAuth | Default provider |
| `chatgpt` | ChatGPT transcription endpoint | Codex OAuth | Requires a compatible ChatGPT session |
| `claude` | Claude voice WebSocket | Claude Desktop session | Cloudflare may reject non-browser clients |
| `local` | OpenAI-compatible Whisper endpoint | Optional local endpoint key | Defaults to `127.0.0.1:8080` |

Provider status is live and must remain honest. Selecting `local` does not silently send audio
to Grok or ChatGPT on failure. Only providers listed in the user's `fallback` configuration
are attempted.

## Developer-only loopback diagnostics

The supported product workflow is the OpenFlow Electron app. Its sidebar provides dictation
history, dictionary, snippets, style, transforms, scratchpad, settings, and the in-app
**Speech Engine** selector.

For development or recovery, start the shim directly:

```bash
python -m openflow serve
```

For the developer diagnostics UI, set `OPENFLOW_CONTROL_CENTER=1`, then open
<http://127.0.0.1:18765/>. Assets under `openflow/static/openflow/` expose provider
status, counters, configuration, and a microphone test bench. This diagnostic page is not a
hosted application, not a product interface, and must not appear in product marketing.

API highlights:

- `GET /health` — active provider and live status
- `GET /v1/providers` — provider capabilities
- `GET/PUT /v1/config` — provider, explicit fallbacks, and local settings
- `POST .../run_remote` — Baseten-compatible transcription contract

The service rejects arbitrary browser origins and must remain bound to loopback.

Configuration lives at `%APPDATA%\\OpenFlow\\config.json` on Windows. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the full contract.

## Electron desktop integration

`python -m openflow start` now finds the Wispr Flow Electron installation already present on
the user's Windows machine, patches it automatically, launches the shim, and opens the OpenFlow
desktop experience. `python -m openflow patch` is still available for explicit/manual patching.
`python -m openflow restore` restores the stock backup (`app.asar.bak-pre-grok-stt`). OpenFlow
does not distribute the third-party app or a patched asar; see
[OPEN_SOURCE.md](OPEN_SOURCE.md).

The patch pipeline (`openflow/patch/ensure.py`) always rebuilds from the stock backup and
applies, in order:

1. **ASR routing** (`patch_asr.py`) — loopback transcription endpoint, local gRPC default,
   raised timeouts, loopback CSP, auto-updater disabled (the build is pinned; Wispr cannot
   auto-update past the patch).
2. **Offline-local sign-in** (`patch_offline_local.py`) — the shell runs on a local offline
   session; the login wall and signed-out dictation states are bypassed.
3. **Rebrand** (`rebrand.py`) — product strings, `package.json`, and the OpenFlow orange
   palette swap.
4. **UI injection** (`inject.py`) — sidebar **Speech Engine** switcher and first-run setup
   panel in the hub renderer, transparent overlay, hidden quota CTA/post-onboarding
   interstitial, Settings restricted to General + System.

The pipeline is verified against **Wispr Flow 1.6.122**. Version-sensitive byte patterns are
checked at every stage; a mismatch fails loudly with the exact marker to report — no partial
patch is installed. No developer UI is shown by default: the loopback diagnostics page is inert
unless `OPENFLOW_CONTROL_CENTER=1` is set.
