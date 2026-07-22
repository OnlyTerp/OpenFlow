from __future__ import annotations

import argparse
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from openflow import __version__
from openflow import cli
from openflow.patch import asar_api
from openflow.patch.ensure import restore_stock
from openflow.providers.registry import _chain_for
from openflow.providers import chatgpt, http_util, registry
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


class TransportTests(unittest.TestCase):
    def test_released_http_session_is_reused(self) -> None:
        first = http_util._acquire_session()
        if first is None:
            self.skipTest("requests unavailable")
        http_util._release_session(first, reusable=True)
        second = http_util._acquire_session()
        try:
            self.assertIs(first, second)
        finally:
            http_util._release_session(second, reusable=False)


    def test_ipv4_preference_keeps_ipv6_fallback(self) -> None:
        ipv6 = (
            socket.AF_INET6,
            socket.SOCK_STREAM,
            0,
            "",
            ("2001:db8::1", 443, 0, 0),
        )
        ipv4 = (
            socket.AF_INET,
            socket.SOCK_STREAM,
            0,
            "",
            ("192.0.2.1", 443),
        )

        ordered = http_util._prefer_ipv4([ipv6, ipv4])

        self.assertEqual([row[0] for row in ordered], [socket.AF_INET, socket.AF_INET6])

    def test_chatgpt_transport_retry_waits_before_retrying(self) -> None:
        with (
            patch.object(
                chatgpt,
                "load_tokens",
                return_value=("token", None, Path("auth.json")),
            ) as load_tokens,
            patch.object(
                chatgpt,
                "post",
                side_effect=[RuntimeError("write timed out"), {"text": "Recovered"}],
            ) as post,
            patch.object(chatgpt, "STT_RETRY_DELAY", 0.75),
            patch.object(chatgpt.time, "sleep") as sleep,
        ):
            result = chatgpt.ChatGptProvider().transcribe(b"wav")

        self.assertEqual(result["text"], "Recovered")
        self.assertEqual(result["provider"], "chatgpt")
        load_tokens.assert_has_calls([call(force=False), call(force=False)])
        self.assertEqual(post.call_count, 2)
        self.assertTrue(post.call_args.kwargs["prefer_ipv4"])
        sleep.assert_called_once_with(0.75)

    def test_chatgpt_401_retry_refreshes_tokens(self) -> None:
        with (
            patch.object(
                chatgpt,
                "load_tokens",
                return_value=("token", None, Path("auth.json")),
            ) as load_tokens,
            patch.object(
                chatgpt,
                "post",
                side_effect=[http_util.HttpError(401), {"text": "Recovered"}],
            ),
            patch.object(chatgpt.time, "sleep"),
        ):
            result = chatgpt.ChatGptProvider().transcribe(b"wav")

        self.assertEqual(result["text"], "Recovered")
        load_tokens.assert_has_calls([call(force=False), call(force=True)])


class StatusCacheTests(unittest.TestCase):
    def test_provider_status_poll_reuses_cached_probe(self) -> None:
        status = Mock()
        status.as_dict.return_value = {
            "id": "chatgpt",
            "ready": True,
            "stt_capable": True,
        }
        provider = Mock()
        provider.status.return_value = status
        cfg = {
            "provider": "chatgpt",
            "providers": {"chatgpt": {"enabled": True}},
        }
        registry.invalidate_status_cache()
        with (
            patch.object(registry, "_providers", {"chatgpt": provider}),
            patch.object(registry, "VALID_PROVIDERS", ("chatgpt",)),
            patch.object(registry.time, "monotonic", side_effect=[10.0, 10.1, 11.0]),
        ):
            first = registry.provider_status_map(cfg=cfg)
            second = registry.provider_status_map(cfg=cfg)
        registry.invalidate_status_cache()

        self.assertTrue(first["chatgpt"]["active"])
        self.assertEqual(first, second)
        provider.status.assert_called_once_with()


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
