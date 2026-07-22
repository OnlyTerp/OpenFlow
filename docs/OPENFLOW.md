# OpenFlow multi-provider STT

OpenFlow is a local Windows controller that routes desktop dictation to one selected speech
provider. The HTTP shim and setup UI run on loopback; OpenFlow has no hosted service.

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

## Local debug UI

Start the shim:

```bash
python -m openflow serve
```

Then open <http://127.0.0.1:18765/>. Assets under `openflow/static/openflow/` provide status,
provider setup, activity counters, settings, and a microphone test bench. This is a local
developer/setup surface, not a hosted web application.

API highlights:

- `GET /health` — active provider and live status
- `GET /v1/providers` — provider capabilities
- `GET/PUT /v1/config` — provider, explicit fallbacks, and local settings
- `POST .../run_remote` — Baseten-compatible transcription contract

The service rejects arbitrary browser origins and must remain bound to loopback.

Configuration lives at `%APPDATA%\\OpenFlow\\config.json` on Windows. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the full contract.

## Desktop integration

The Windows preview uses the explicit `python -m openflow patch` command to integrate with a
Wispr Flow installation already present on the user's machine. `python -m openflow restore`
restores the stock backup. OpenFlow does not distribute the third-party app or any patched
asar; see [OPEN_SOURCE.md](OPEN_SOURCE.md).
