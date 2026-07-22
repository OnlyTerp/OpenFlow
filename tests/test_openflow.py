from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openflow import __version__
from openflow import cli
from openflow.patch import asar_api
from openflow.patch.ensure import restore_stock
from openflow.providers.registry import _chain_for
from openflow.server import app


ROOT = Path(__file__).resolve().parents[1]


class CleanupTests(unittest.TestCase):
    def test_join_preserves_every_chunk(self) -> None:
        self.assertEqual(app._join_prev_and_chunk("hello world", "again"), "hello world again")
        self.assertEqual(app._join_prev_and_chunk("", "only"), "only")
        self.assertEqual(app._join_prev_and_chunk("previous", ""), "previous")

    def test_faithfulness_rejects_summary(self) -> None:
        original = ("word " * 80).strip()
        self.assertFalse(app.format_is_faithful(original, "just a few words"))

    def test_cleanup_removes_fillers_and_stutter(self) -> None:
        self.assertEqual(app.local_light_cleanup("um I I think so"), "I think so")

    def test_builtin_lexicon_repairs_oauth(self) -> None:
        cleaned = app.apply_lexicon("set up o off please", app._compile_lexicon())
        self.assertIn("oauth", cleaned.lower())


class PrivacyTests(unittest.TestCase):
    def test_fallbacks_are_opt_in(self) -> None:
        self.assertEqual(_chain_for("local", {"fallback": []}), ["local"])
        self.assertEqual(
            _chain_for("local", {"fallback": ["grok", "grok", "unknown"]}),
            ["local", "grok"],
        )

    def test_arbitrary_web_origins_are_rejected(self) -> None:
        self.assertFalse(app._origin_allowed("https://attacker.example"))
        self.assertFalse(app._origin_allowed("http://localhost:3000"))
        self.assertTrue(app._origin_allowed(f"http://127.0.0.1:{app.PORT}"))
        self.assertTrue(app._origin_allowed("null"))
        self.assertTrue(app._origin_allowed(None))

    def test_failed_audio_retention_is_off_by_default(self) -> None:
        self.assertIsNone(app.DEBUG_AUDIO_DIR)


class DesktopPatchTests(unittest.TestCase):
    def test_newest_app_version_uses_numeric_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "app-1.6.30").mkdir()
            newest = root / "app-1.6.122"
            newest.mkdir()
            self.assertEqual(asar_api.newest_app_dir(root), newest)

    def test_verification_rejects_subscription_bypass_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            asar = Path(temp) / "app.asar"
            safe_payload = b"\n".join(asar_api.REQUIRED_MARKERS.values())
            asar.write_bytes(safe_payload)
            ok, checks = asar_api.verify_asar(asar)
            self.assertTrue(ok, checks)

            asar.write_bytes(safe_payload + b"\ngrok-flow-pro")
            ok, checks = asar_api.verify_asar(asar)
            self.assertFalse(ok)
            self.assertFalse(checks["no subscription bypass"])

    def test_restore_uses_stock_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            resources = root / "app-1.6.122" / "resources"
            resources.mkdir(parents=True)
            asar = resources / "app.asar"
            asar.write_bytes(b"patched")
            asar.with_name("app.asar.bak-pre-grok-stt").write_bytes(b"stock")

            self.assertEqual(restore_stock(root), asar)
            self.assertEqual(asar.read_bytes(), b"stock")


class PackagingTests(unittest.TestCase):
    def test_python_and_node_versions_match(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["name"], "openflow")
        self.assertEqual(package["version"], __version__)

    def test_windows_path_translation_has_no_fixed_username(self) -> None:
        path = cli._windows_path_for_wsl(r"C:\Users\Alice\AppData\Local")
        self.assertEqual(path, Path("/mnt/c/Users/Alice/AppData/Local"))

    def test_installer_never_copies_private_examples(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            destination = base / "install"
            package = source / "openflow"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "__pycache__").mkdir()
            (package / "__pycache__" / "private.pyc").write_bytes(b"private")
            (source / "format_examples.json").write_text(
                '{"private": "dictation"}\n', encoding="utf-8"
            )
            for name in cli._INSTALL_FILES:
                if name != "launch-openflow.vbs":
                    (source / name).write_text("{}\n", encoding="utf-8")

            args = argparse.Namespace(dir=str(destination), no_shortcuts=True)
            with patch.object(cli, "_repo_root", return_value=source):
                self.assertEqual(cli.cmd_install(args), 0)

            self.assertFalse((destination / "format_examples.json").exists())
            self.assertFalse((destination / "openflow" / "__pycache__").exists())
            self.assertTrue((destination / "launch-openflow.vbs").is_file())


if __name__ == "__main__":
    unittest.main()
