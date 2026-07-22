# OpenFlow Electron desktop integration

OpenFlow 0.2 uses a Wispr Flow installation already present on the user's Windows machine as
its Electron shell for global push-to-talk, the recording overlay, dictation history,
engine switching, and paste-at-cursor behavior. This installed Electron experience is the
OpenFlow product surface. The public repository ships source-only integration tooling, not
the third-party desktop binary.

## Boundary

- The user installs and licenses Wispr Flow separately.
- OpenFlow never downloads, commits, uploads, or releases an asar.
- `python -m openflow patch` is an explicit local action.
- The first patch preserves `app.asar.bak-pre-grok-stt`.
- `python -m openflow restore` copies that stock backup back into place.
- Normal `openflow start` does not silently re-patch a third-party application.
- Login, subscription, quota, update, and account controls remain stock.

See [OPEN_SOURCE.md](OPEN_SOURCE.md) for the publication policy.

## Patch behavior

`openflow/patch/patch_asr.py` performs narrow, version-sensitive transformations:

1. Redirect the Baseten-compatible `run_remote` URL to
   `http://127.0.0.1:18765/environments/production/run_remote`.
2. Enable the packaged gRPC override and default it to a non-racing local endpoint.
3. Raise transcription and processing timeouts for local/provider latency.
4. Extend the renderer CSP so it may contact the loopback shim.

Post-patch verification requires those markers and fails if a known subscription-bypass
marker is present.

## Install and launch

Close Wispr Flow before patching:

```bat
npm ci
python -m openflow install
python -m openflow patch
python -m openflow start
```

The install root is `%LOCALAPPDATA%\\OpenFlow`. Desktop and Startup shortcuts point to
`launch-openflow.vbs` there. The launcher starts the shim without a console window and opens
the OpenFlow Electron app.

Choose Grok, GPT, Claude, or Local from the app's **Speech Engine** control. The loopback page
at <http://127.0.0.1:18765/> is developer diagnostics only and is not a product interface.

## After a desktop-app update

An update may replace the modified asar. Close the desktop app and run:

```bat
python -m openflow patch
```

If marker matching fails, do not force a partial output into place. Restore stock, open an
issue containing only the Wispr version and OpenFlow error text, and never attach extracted
source or an asar.

## Restore

```bat
python -m openflow restore
```

Restore fails rather than guessing when the stock backup is missing.

## Troubleshooting

| Symptom | Check |
|---|---|
| Shim offline | `python -m openflow status` |
| Desktop still uses stock transcription | Close the app, run `python -m openflow patch`, relaunch |
| Provider unavailable | Open `/health` and inspect the selected provider's honest status |
| Local Whisper unavailable | Start the configured server and verify its URL in the dashboard |
| Long dictation truncates | Run the offline tests; the final `llm_text` must include `prev_asr_text` |
| Patch patterns no longer match | Restore stock and report the app version; do not publish vendor code |

## Windows and WSL

The shim must run on the same OS loopback as the desktop shell. Under WSL2 NAT,
`127.0.0.1` may not cross between Linux and Windows. The supported desktop path therefore uses
Windows Python and Windows provider credential stores.
