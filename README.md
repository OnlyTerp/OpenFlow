# OpenFlow

**Local-first, multi-engine dictation for Windows.** OpenFlow routes speech from a desktop
dictation shell to Grok, ChatGPT, Claude Desktop, or an OpenAI-compatible local Whisper
endpoint. The controller and provider integrations run on your machine; OpenFlow has no
hosted service.

```text
microphone → desktop shell → OpenFlow shim on 127.0.0.1:18765
                            → selected speech provider
```

> **Release status:** OpenFlow 0.2.0 is a Windows preview. The current desktop integration
> patches a Wispr Flow installation already owned and installed by the user. OpenFlow does
> not bundle Wispr code or binaries, is not affiliated with Wispr, and may need to be
> re-patched after a Wispr update.

## What ships

| Component | Purpose |
|---|---|
| `openflow/server` | Loopback-only HTTP transcription shim and debug dashboard |
| `openflow/providers` | Grok, ChatGPT, Claude Desktop, and local Whisper adapters |
| `openflow/patch` | Source-only tooling that modifies the user's local desktop install |
| `openflow/static` | Dependency-free local status, setup, and test-bench UI |
| `openflow/host.py` | Silent Windows launcher for the shim and desktop shell |

No proprietary asar, extracted vendor source, credentials, recordings, or dictation history
belongs in this repository.

## Privacy and security defaults

- The HTTP service binds to `127.0.0.1` by default.
- Arbitrary website origins are rejected; only the bundled local UI and local desktop shell
  receive cross-origin access.
- Provider fallback is **opt-in**. Failed local transcription never sends audio to a cloud
  provider unless that provider is explicitly present in `fallback`.
- Failed recordings are **not retained**. Set `WISPR_GROK_DEBUG_AUDIO` to a directory only
  when you intentionally need local diagnostic recordings.
- `format_examples.json` is private, gitignored, and never copied by the installer.
- Credentials stay in each provider's existing local credential store. OpenFlow never copies
  them into the repository or install payload.

Never expose port `18765` to a LAN or the public internet.

## Requirements

- Windows 11
- Python 3.11 or newer on Windows `PATH`
- Node.js 22.12 or newer, used only to unpack and repack the local Electron asar
- [Wispr Flow](https://wisprflow.ai) installed by the user
- At least one configured speech provider:
  - SuperGrok / Grok CLI OAuth
  - ChatGPT / Codex OAuth
  - Claude Desktop
  - OpenAI-compatible local Whisper server

Provider and desktop-app terms still apply. OpenFlow does not grant access to a paid service.

## Install

Run from Command Prompt, PowerShell, or Git Bash:

```bat
git clone https://github.com/OnlyTerp/OpenFlow.git
cd OpenFlow
npm ci
python -m openflow install
python -m openflow patch
python -m openflow start
```

`install` deploys the public runtime to `%LOCALAPPDATA%\OpenFlow` and creates Desktop and
Startup shortcuts. `patch` is intentionally separate: it is the explicit step that backs up
and modifies the user's local desktop asar. It never downloads or publishes a vendor binary.

The installed launcher is:

```text
%LOCALAPPDATA%\OpenFlow\launch-openflow.vbs
```

### Connect a speech provider

Open the local dashboard at <http://127.0.0.1:18765/> after the shim starts. The public
integration keeps the desktop application's account and subscription UI stock.

| Provider | Connection path |
|---|---|
| Grok | `grok login --oauth` |
| ChatGPT | `codex login` |
| Claude | Sign in to Claude Desktop |
| Local | Enter an OpenAI-compatible `/v1/audio/transcriptions` URL |

Select an engine before dictating. The selected provider is authoritative unless you
explicitly configure fallback providers.

## Commands

| Command | Action |
|---|---|
| `python -m openflow install` | Deploy runtime and Windows shortcuts |
| `python -m openflow start` | Start the shim silently and launch the desktop shell |
| `python -m openflow serve` | Run only the shim in the foreground |
| `python -m openflow status` | Print `GET /health` and exit nonzero when offline |
| `python -m openflow patch` | Back up and patch the current local desktop asar |
| `python -m openflow restore` | Restore the stock asar backup |

After a Wispr update, close Wispr and run `python -m openflow patch` again. OpenFlow does not
silently modify third-party application files during normal startup.

## Configuration

User configuration lives outside the repository:

- Windows: `%APPDATA%\OpenFlow\config.json`
- Other development hosts: `~/.openflow/config.json`
- Override: `OPENFLOW_CONFIG=/path/to/config.json`

The default local Whisper endpoint is
`http://127.0.0.1:8080/v1/audio/transcriptions`. Provider selection, enabled providers, local
endpoint settings, and explicit fallbacks are stored in the configuration file.

Useful development overrides:

| Variable | Default | Purpose |
|---|---|---|
| `WISPR_GROK_HOST` | `127.0.0.1` | Shim bind address |
| `WISPR_GROK_PORT` | `18765` | Shim port |
| `WISPR_GROK_DEBUG_AUDIO` | unset | Opt-in failed-audio directory |
| `WISPR_GROK_EXAMPLES` | install-root `format_examples.json` | Private cleanup examples |
| `OPENFLOW_CONFIG` | platform config path | Isolated config for development/tests |

## Development

The Python runtime uses the standard library plus provider-specific local clients. The only
Node dependency is `@electron/asar` for the explicit patch command.

```bash
npm ci
python -m unittest discover -s tests -v
python -m openflow --help
python -m openflow serve
```

Then open <http://127.0.0.1:18765/> and exercise the local status/setup surface.

Architecture and design references:

- [Architecture](docs/ARCHITECTURE.md)
- [Open-source boundary](docs/OPEN_SOURCE.md)
- [Desktop integration history](docs/LEGACY-SHELL.md)
- [Brand](docs/BRAND.md)
- [Design](docs/DESIGN.md)

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Provider status must remain
honest: never report an engine as ready unless its real authentication and transcription path
are available. Security reports belong in [SECURITY.md](SECURITY.md), not a public issue.

## Legal

OpenFlow-authored code and assets are MIT licensed; see [LICENSE](LICENSE). The license does
not cover Wispr Flow binaries, source, trademarks, or services. Provider names are used
nominatively. OpenFlow is not affiliated with or endorsed by Wispr, xAI, OpenAI, or Anthropic.
