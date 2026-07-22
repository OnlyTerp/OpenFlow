# OpenFlow layout (v0.2)

Single product package. Single install root. No dual trees.

## Source (git)

```
OpenFlow/
  openflow/                 # Python package (the product)
    __main__.py             # python -m openflow
    cli.py                  # install | start | serve | status | patch | restore
    host.py                 # silent Windows host (no CMD windows)
    config.py               # user config
    auth.py                 # connect-engine flows
    insights.py
    server/
      app.py                # ThreadingHTTPServer + STT pipeline
    providers/              # grok | chatgpt | claude | local
    patch/                  # explicit route/timeout patch + stock restore
      ensure.py
      patch_asr.py
      asar_api.py
    static/openflow/        # shim debug + setup UI
  launch-openflow.vbs       # zero-console entry
  docs/
  package.json              # @electron/asar for patch pack/extract only
  tests/                    # offline regression suite
  CONTRIBUTING.md
  SECURITY.md
```

## Install root (runtime)

```
%LOCALAPPDATA%\OpenFlow\
  openflow\                 # copy of package
  launch-openflow.vbs
  node_modules\             # asar tooling
  logs\
  OPENFLOW_HOME
```

Desktop + Startup shortcuts point **only** here. The install command never copies private
cleanup examples, credentials, recordings, or source-control metadata.

## What is not shipped

- Wispr / Electron `app.asar` binaries
- User tokens, `format_examples.json` mined from private history
- Dual install copies
