"""OpenFlow — local-first multi-engine dictation.

Package layout:
  openflow/
    server/     HTTP STT shim (Grok / ChatGPT / Claude / Local)
    providers/  STT plugins
    patch/      Desktop Electron shell patch tools (user's own install only)
    static/     Developer diagnostics / setup UI (not the product surface)
    host.py     Silent Windows launcher
    config.py   User config (~/.openflow or %APPDATA%\\OpenFlow)
    auth.py     Connect-engine OAuth helpers
    cli.py      `python -m openflow` entry
"""

__version__ = "0.2.0"
__all__ = ["__version__"]
