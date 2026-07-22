# Contributing to OpenFlow

OpenFlow handles microphone audio and local authentication state. Privacy and honest provider
status are release requirements, not optional polish.

## Development setup
Requirements: Python 3.11+, Node.js 22.12+, and Git.

```bash
npm ci
python -m unittest discover -s tests -v
python -m openflow --help
```

The test suite is offline and must not require real provider credentials. For a local smoke
test, isolate configuration and choose a non-production port:

```bash
OPENFLOW_CONFIG=/tmp/openflow-dev.json WISPR_GROK_PORT=18766 \
  python -m openflow serve
```

Open `http://127.0.0.1:18766/`, then stop the process when finished.

## Repository boundaries

Canonical runtime code lives under `openflow/`:

- `openflow/server`: loopback HTTP API
- `openflow/providers`: speech-provider adapters and registry
- `openflow/patch`: explicit local desktop-integration tooling
- `openflow/static`: local debug/setup UI
- `tests`: offline regression tests

Do not commit any of the following:

- `app.asar`, extracted vendor bundles, or copied vendor source
- OAuth files, cookies, bearer tokens, API keys, or session databases
- dictation audio, transcripts, history, mined examples, or runtime logs
- vendor logos, product screenshots, or trademarked assets

The relevant exclusions are enforced in `.gitignore`; run a secret scan before opening a pull
request.

## Provider contract

A provider implements `status()` and `transcribe()` using the types in
`openflow/providers/base.py`.

- `status().ready` must reflect the real local authentication and runtime state.
- `stt_capable` must be false when the provider cannot currently accept speech.
- Never log credentials, request audio, or transcript text.
- Never add an implicit cloud fallback. Audio may leave the selected provider only through a
  fallback explicitly configured by the user.
- Normalize provider failures to the existing `SttError` hierarchy without hiding the real
  failure from status/metrics.

## Pull requests

Keep changes focused and include an observable regression test for new behavior. Before
submitting:

```bash
npm test
python -m compileall -q openflow tests
python -m openflow --version
```

Also verify that `git status --ignored` contains no credentials, recordings, logs, extracted
asars, or private examples staged for publication.

Changes to desktop patch patterns must be tested only against software installed and licensed
by the contributor. Never attach the resulting vendor binary to an issue or pull request.
