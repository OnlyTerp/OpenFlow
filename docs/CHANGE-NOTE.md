# OpenFlow 0.2.0 release notes

OpenFlow 0.2.0 is the first public-preview layout: one Python package, one Windows install
root, explicit provider selection, and a documented open-source boundary.

## Runtime

- Added the canonical `python -m openflow` command surface:
  `install`, `start`, `serve`, `status`, `patch`, and `restore`.
- Consolidated the server, providers, configuration, setup UI, host, and patch helpers under
  `openflow/`; removed the duplicated prototype trees.
- Added Grok, ChatGPT, Claude Desktop, and OpenAI-compatible local Whisper providers behind
  one registry.
- Preserved the long-dictation invariant: the final formatted response contains the complete
  utterance, not only the last audio chunk.
- Added a silent Windows launcher and a single `%LOCALAPPDATA%\\OpenFlow` runtime root.

## Privacy and security

- Removed implicit Grok/ChatGPT fallback. Only user-configured fallback providers receive a
  failed transcription attempt.
- Disabled failed-audio retention by default; diagnostics require an explicit
  `WISPR_GROK_DEBUG_AUDIO` directory.
- Removed transcript excerpts from cleanup logs.
- Restricted local API CORS to the bundled loopback UI and local desktop origin.
- Stopped copying private `format_examples.json` data into install payloads.
- Removed machine-specific usernames and private deployment paths.

## Public desktop-integration boundary

The public patch changes transcription routing, gRPC race behavior, processing timeouts, and
the renderer's loopback CSP. It does **not** bypass login, subscription, quota, or update
controls. Patching is explicit and creates a stock backup; normal startup does not silently
rewrite the third-party app.

OpenFlow does not publish patched asars, extracted vendor source, vendor assets, vendor
screenshots, credentials, recordings, transcripts, or runtime logs.

## Repository

- Added offline regression coverage for cleanup, explicit fallback, origin restrictions,
  version consistency, path portability, and private-data exclusion.
- Added `CONTRIBUTING.md` and `SECURITY.md`.
- Synchronized Python and Node metadata at version `0.2.0`.
- Documented clean install, restore, security scanning, and GitHub metadata.
