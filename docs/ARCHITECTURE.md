# OpenFlow architecture

OpenFlow is three cooperating layers, each replaceable on its own:

```
┌──────────────────────────────────────────────────────────────────┐
│ PRESENTATION                                                       │
│  user-installed desktop shell ───── hotkey · overlay · paste          │
│  OpenFlow local UI (openflow/static) ─ status · engine · test bench   │
│  overlay.html ───────────────────── future standalone HUD spec         │
├──────────────────────────────────────────────────────────────────┤
│ LOCAL API  —  http://127.0.0.1:18765                               │
│  openflow/server/app.py ── /health /v1/providers /v1/config /metrics │
│                            POST .../run_remote                         │
├──────────────────────────────────────────────────────────────────┤
│ PROVIDERS  —  openflow/providers registry                           │
│  grok · chatgpt · claude · local OpenAI-compatible Whisper           │
│  deterministic local cleanup; optional explicit Grok format pass     │
└──────────────────────────────────────────────────────────────────┘
```

Everything binds to loopback by default. Audio egress goes only to the selected transcription
provider and explicit fallbacks. If the optional Grok LLM format pass is enabled, transcript
text also goes to Grok; it is disabled by default.

## Local setup UI

`openflow/static/openflow/` is a dependency-free SPA (no build step) served by the shim itself
at `GET /` (and `/ui/*`). It is OpenFlow's local setup and test-bench surface. OS-global
hotkey, recording overlay, and paste behavior come from the separately installed desktop
shell:

| Route | Screen | Backing API |
|-------|--------|-------------|
| `#/home` | status card, quick switch, shim stats, **test bench** | `/health`, `POST /v1/run_remote` |
| `#/engine` | provider cards: honest status, enable, fallback, make-active | `/health`, `PUT /v1/config` |
| `#/activity` | counters, per-engine ok/fail, bench history | `/metrics`, `/health`, localStorage |
| `#/settings` | shim info, accent, hotkey preference, about | `/health`, `/v1/config` |
| first-run | 5-step onboarding (connect → choose → hotkey → test) | same |

The test bench captures mic audio in the browser, resamples to **16 kHz mono PCM16**, wraps a
44-byte RIFF header, base64s it, and POSTs the identical `run_remote` payload a desktop shell
sends. A generated test tone does the same without a mic, so CI/headless can smoke the full
pipeline.

### `window.openflowBridge` (shell contract)

The future desktop shell injects this object; the control center already probes for it:

```ts
interface OpenFlowBridge {
  registerHotkey(combo: string): Promise<unknown>;  // OS-global push-to-talk
  pasteText(text: string): Promise<unknown>;        // paste at cursor, focused app
}
```

Absent the bridge: hotkey combos persist to `localStorage` as preferences (labelled as a
local stub), and "paste" degrades to clipboard write with an explicit toast. No silent fakes.

## Shim

`openflow/server/app.py` is a stdlib `ThreadingHTTPServer` on `127.0.0.1:18765`
(`WISPR_GROK_HOST` / `WISPR_GROK_PORT` override it). Requests from arbitrary web origins are
rejected; the service must not be exposed beyond loopback.

### Endpoints

- `GET /health` — `{ok, brand, provider, providers, config, uptime_s, requests,
  last_provider, last_stt_ok, last_stt_latency_s, last_stt_error, stt, local_cleanup, …}`
- `GET /v1/providers` — `{active, providers}` where each entry is
  `{id, label, ready, detail, auth_path, stt_capable, error, enabled, active, …extra}`
- `GET /v1/config` — `{path, config}`; `PUT`/`POST` merge-patches and persists.
- `GET /metrics` — counters (`requests`, `stt_ok`, `stt_fail`), averages, `lexicon_rules`,
  `few_shots`, `provider_stats.by_provider.{ok,fail}`.
- `POST <path ending in>run_remote` — transcription (contract below).
- `GET /`, `/ui/*`, `/static/*`, `/app.css`, `/app.js` — control center static files with a
  path-traversal guard.

### `run_remote` contract

Request:

```json
{
  "request": {
    "audio": "<base64 WAV (RIFF) or raw PCM16, 16 kHz mono>",
    "language": "en",
    "pipeline": ["transcribe", "format"],
    "prev_asr_text": "<earlier chunks joined, final call only>"
  }
}
```

Response: `{status, asr_text, llm_text, detected_language, asr_time, llm_time, total_time,
component_times, error_message?}`.

**Multi-chunk rule (critical):** long hold-to-talk arrives as several HTTP calls. Mid-stream
calls return `asr_text` for *that chunk only*; the final call (`pipeline` contains `"format"`)
carries `prev_asr_text` and its `llm_text` must be the **full utterance** — paste consumes the
last non-empty `llm_text`. A format-only finalize (no audio, `prev_asr_text` present) is also
valid and returns `{status:"formatted", llm_text: full}`.

### Provider plugin contract (`openflow/providers/base.py`)

```python
class SttProvider(Protocol):
    id: str
    label: str
    def status(self) -> ProviderStatus: ...          # honest, read live session files
    def transcribe(self, wav_bytes: bytes, language: str = "en") -> dict: ...
```

`ProviderStatus`: `{id, label, ready, detail, auth_path, stt_capable, error, extra}`.
`ready=False` + `auth_path=None` → UI shows *needs login*; `auth_path` set +
`stt_capable=False` → UI shows *limited*. The registry
(`openflow/providers/registry.py`) instantiates all providers, resolves the active id from
config, walks only the user's explicit `fallback` list on failure, and records per-provider
ok/fail stats.

| Provider | Transport | Auth source |
|----------|-----------|-------------|
| `grok` | `POST https://api.x.ai/v1/stt` (multipart WAV, Bearer) | `~/.grok/auth.json` |
| `chatgpt` | `POST https://chatgpt.com/backend-api/transcribe` | `~/.codex/auth.json` (ChatGPT OAuth + account id) |
| `claude` | `WSS wss://claude.ai/api/ws/speech_to_text/voice_stream` (binary PCM16 + KeepAlive/CloseStream) | Claude Desktop Electron cookie store (`sessionKey`, `lastActiveOrg`) |

Claude caveat: the WebSocket is behind Cloudflare; raw non-browser clients are often refused
(403). Session detection works and the UI surfaces runtime failures on the Activity page.

### Config

`openflow/config.py` — single JSON at `%APPDATA%\OpenFlow\config.json` (Windows),
`$XDG_CONFIG_HOME/OpenFlow/config.json`, or `~/.openflow/config.json`
(`OPENFLOW_CONFIG` overrides). Schema:

```json
{
  "provider": "grok",
  "fallback": ["chatgpt"],
  "providers": { "grok": {"enabled": true}, "chatgpt": {"enabled": true}, "claude": {"enabled": true} },
  "ui": { "brand": "openflow", "accent": "#ff6b2c" }
}
```

Defaults merge over missing keys; file is mtime-cached and reloaded on change.

### Cleanup pipeline

After STT, `local_light_cleanup` (stutter/filler fixes and optional private lexicon rules)
runs without network access. An optional Grok LLM format pass
(`WISPR_GROK_LLM_FORMAT=true`) can polish further, but sends transcript text to Grok and is
disabled by default. `format_examples.json` remains local, gitignored, and absent from the
installed payload unless the user deliberately supplies it.

## Desktop integration

OpenFlow's Windows desktop integration uses source-only tools under `openflow/patch` to
modify a Wispr Flow installation already present on the user's machine. The patch redirects
the desktop shell's transcription request to the loopback shim and applies OpenFlow's local
integration assets. Patching is an explicit command, creates a stock backup, and does not
run silently during normal startup.

No patched asar, extracted vendor source, vendor screenshot, or vendor asset is distributed.
The patch history and operational constraints are documented in
[LEGACY-SHELL.md](LEGACY-SHELL.md); the publication boundary is
[OPEN_SOURCE.md](OPEN_SOURCE.md).

## Platform notes

- The shim binds the **OS where the shell runs**. For a Windows shell, run the shim with
  Windows Python — WSL `127.0.0.1` is a different loopback under NAT networking.
- Auth tokens are read from the user's own CLI/desktop sessions; sync `~/.grok/auth.json` /
  `~/.codex/auth.json` to the OS running the shim.
- Static UI is plain web assets: wrapping in Tauri later needs no rewrite, only the bridge.
