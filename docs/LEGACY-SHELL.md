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
- The first patch preserves `app.asar.bak-pre-grok-stt` (created only while the live asar
  is still stock; every later run rebuilds from that backup).
- `python -m openflow restore` copies that stock backup back into place.
- The pipeline targets **Wispr Flow 1.6.122**: sign-in is replaced by a local offline
  session, cloud-only chrome (quota CTA, post-onboarding interstitial, account tabs) is
  hidden, the auto-updater is disabled (update pin), and the UI is rebranded to OpenFlow.

See [OPEN_SOURCE.md](OPEN_SOURCE.md) for the publication policy.

## Patch behavior

`openflow/patch/ensure.py` orchestrates the pipeline. It extracts the stock backup into a
Windows-visible staging directory, runs the stages below, repacks with the stock build's
unpack globs (`.node`/`.dll`/`.exe` stay unpacked), verifies the full marker set, and swaps
the live asar:

1. `patch_asr.py`:
   - Redirect the Baseten-compatible `run_remote` URL to
     `http://127.0.0.1:18765/environments/production/run_remote`.
   - Enable the packaged gRPC override and default it to a non-racing local endpoint.
   - Raise transcription (60s) and processing (120s) timeouts for local/provider latency.
   - Extend the renderer CSP (`connect-src` and `frame-src`) so it may contact the
     loopback shim.
   - Disable `checkForUpdates` (`openflow-disable-updates`) so the pinned 1.6.122 build is
     not silently replaced by an unpatched update.
2. `patch_offline_local.py` — local offline sign-in (no login wall, dictation never
   signed out; markers `grok-flow-offline-local`, `grok-flow-no-login`,
   `grok-flow-force-signed-in`).
3. `rebrand.py` — product strings, `package.json` fields, and the safe color list
   (Wispr greens → OpenFlow orange), with `openflow-rebrand` marker.
4. `inject.py` — theme/overlay assets from `openflow/patch/assets/` (Speech Engine
   switcher, setup panel, transparent overlay) plus hub JS patches that hide the quota CTA,
   skip the post-onboarding interstitial, and restrict Settings to General + System.

Post-patch verification requires every pipeline marker (ASR routing, timeouts, CSP,
offline-local, hub chrome, rebrand, speech engine UI) and fails if the stock Baseten URLs
are still present. If byte patterns stop matching a future Wispr build, the pipeline fails
loudly with the version to report.

## Install and launch

Close Wispr Flow before patching:

```bat
npm ci
python -m openflow install
python -m openflow start
```

The install root is `%LOCALAPPDATA%\\OpenFlow`. Desktop and Startup shortcuts point to
`launch-openflow.vbs` there. The launcher starts the shim without a console window and opens
the OpenFlow Electron app.

Choose Grok, GPT, Claude, or Local from the app's **Speech Engine** control in the bottom-left
corner of the patched Wispr Flow window. The loopback page at <http://127.0.0.1:18765/> is
developer diagnostics only and is not a product interface.

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
| Desktop still uses stock transcription | Close the app, run `python -m openflow start` again (it re-patches automatically), or run `python -m openflow patch` |
| Provider unavailable | Open `/health` and inspect the selected provider's honest status |
| Local Whisper unavailable | Start the configured server and verify its URL in the dashboard |
| Long dictation truncates | Run the offline tests; the final `llm_text` must include `prev_asr_text` |
| Patch patterns no longer match | Restore stock and report the app version; do not publish vendor code |

## Windows and WSL

The shim must run on the same OS loopback as the desktop shell. Under WSL2 NAT,
`127.0.0.1` may not cross between Linux and Windows. The supported desktop path therefore uses
Windows Python and Windows provider credential stores.
