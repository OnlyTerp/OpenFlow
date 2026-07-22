# Open-source boundary

OpenFlow publishes only code and assets authored for this project. The current desktop
integration operates on a third-party application already installed by the user; no vendor
binary is part of the distribution.

## Publication matrix

| Layer | Publish | Boundary |
|---|---:|---|
| `openflow/server` and `openflow/config.py` | yes | OpenFlow-authored loopback shim |
| `openflow/providers` | yes | Uses each provider's existing local authentication |
| `openflow/static` | yes | Original local debug/setup UI |
| `openflow/patch` | yes | Source-only tooling; acts on the user's local install |
| `openflow/host.py` and `launch-openflow.vbs` | yes | Original local launchers |
| `tests`, `docs`, OpenFlow assets | yes | Synthetic fixtures and original project material only |
| Wispr binaries, extracted source, logos, screenshots | **never** | Proprietary third-party material |
| credentials, recordings, transcripts, histories, logs | **never** | User-private data |

The MIT license covers only OpenFlow-authored material. It does not grant rights to Wispr Flow
or any provider's software, trademarks, accounts, or services.

## Never publish

- `app.asar`, `app.asar.*`, `asar-extract*/`, or `asar-work*/`
- extracted or copied vendor JavaScript, binaries, logos, or product screenshots
- `auth.json`, cookies, bearer tokens, API keys, or session files
- `flow.sqlite`, dictionary exports, recordings, transcripts, or dictation histories
- `format_examples.json` generated from private speech
- `logs/`, crash dumps, PID files, or machine-specific release helpers

`.gitignore` covers these paths. Ignore rules do not clean Git history; scan both the current
tree and every commit before changing repository visibility.

## Runtime privacy invariants

1. Bind the HTTP service to loopback by default.
2. Reject arbitrary browser origins.
3. Never retain failed audio unless the user explicitly configures a debug directory.
4. Never log transcript bodies or credential values.
5. Never route audio to an implicit fallback provider.
6. Never copy private cleanup examples or credentials into an install payload.
7. Never modify the third-party desktop asar during ordinary startup; patching is an explicit
   command and creates a stock backup.

Regression coverage for these rules lives in `tests/test_openflow.py`.

## Pre-publication checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q openflow tests
npm ci
npm test
gitleaks git --redact .
gitleaks dir --redact openflow
```

Also inspect `git status --short --ignored` before staging. A clean scanner result does not
authorize third-party material; the publication matrix above still applies.

## Repository metadata

Recommended GitHub description:

> Local-first, multi-engine dictation controller for Windows.

Recommended topics: `dictation`, `speech-to-text`, `local-first`, `windows`, `whisper`.

Security reports should use GitHub's private vulnerability-reporting flow described in
[`SECURITY.md`](../SECURITY.md).
