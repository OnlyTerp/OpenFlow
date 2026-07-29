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

    def _build_stock_extract(self, extract: Path) -> None:
        """Synthetic stock 1.6.122-shaped asar extraction for the pipeline."""
        from openflow.patch import inject, patch_asr, patch_offline_local

        main_dir = extract / ".webpack" / "main"
        hub = extract / ".webpack" / "renderer" / "hub"
        overlay = extract / ".webpack" / "renderer" / "overlay"
        for d in (main_dir, hub, overlay):
            d.mkdir(parents=True)

        stock_main = b";".join(
            [
                patch_asr.OLD_PROD,
                patch_asr.OLD_STAGE,
                b"if(!e.app.isPackaged){const t=process.env.FLOW_GRPC_URL_OVERRIDE",
                b"if(1){const e=process.env.FLOW_GRPC_URL_OVERRIDE?.trim();"
                b'if(e){const t=process.env.FLOW_GRPC_MODEL_ID_OVERRIDE?.trim()??"",'
                b'n=process.env.FLOW_GRPC_ENVIRONMENT_OVERRIDE?.trim()??"";'
                b'return ze().info("Using dev gRPC route override from env",'
                b"{customAttributes:{url:e,modelId:t,environment:n}}),"
                b"{modelId:t,environment:n,url:e}}}",
                b"TRANSCRIPTION_TIMEOUT=1e4",
                b',V=3e4,G=3e4,Y=12e4,K=6e4,Z=3145728,X=20971520,'
                b'J="Pre-Login Feedback",ee=200,te=24e3',
                patch_asr.CSP_CONNECT_END,
                patch_asr.CSP_FRAME_END,
                patch_asr._UPDATER_OLD,
            ]
            + [old for old, _new, _label in patch_offline_local._PATCHES_MAIN]
        )
        (main_dir / "index.js").write_bytes(stock_main)

        stock_hub = b";".join(
            [old for old, _new, _label in patch_offline_local._PATCHES_HUB]
            + [old for old, _new, _marker in inject._HUB_PATCHES]
            + [b'"Wispr Flow"', b'"hub_plan_name_basic":"Basic"']
        )
        (hub / "index.js").write_bytes(stock_hub)
        (hub / "index.html").write_text(
            "<html><head></head><body></body></html>", encoding="utf-8"
        )
        (overlay / "index.html").write_text(
            '<html><head></head><body style="overflow: hidden"></body></html>',
            encoding="utf-8",
        )
        (extract / "package.json").write_text(
            json.dumps(
                {
                    "name": "wispr-flow",
                    "productName": "Wispr Flow",
                    "description": "Wispr Flow",
                    "author": {"name": "Wispr Flow"},
                    "version": "1.6.122",
                }
            ),
            encoding="utf-8",
        )

    def test_pipeline_marks_patched_asar(self) -> None:
        """Full pipeline output must satisfy the complete verification set."""
        from openflow.patch import inject, patch_asr, patch_offline_local, rebrand

        with tempfile.TemporaryDirectory() as temp:
            extract = Path(temp) / "extract"
            self._build_stock_extract(extract)

            patch_asr.patch(extract / ".webpack" / "main" / "index.js")
            patch_offline_local.patch_extract(extract)
            rebrand.rebrand(extract)
            inject.run(extract)

            blob = b"\n".join(
                p.read_bytes() for p in sorted(extract.rglob("*")) if p.is_file()
            )
            missing = [
                name
                for name, marker in asar_api.REQUIRED_MARKERS.items()
                if marker not in blob
            ]
            self.assertEqual(missing, [])
            for url in asar_api.STOCK_URLS:
                self.assertNotIn(url, blob)

    def test_verification_requires_full_marker_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            asar = Path(temp) / "app.asar"
            full_payload = b"\n".join(asar_api.REQUIRED_MARKERS.values())
            asar.write_bytes(full_payload)
            ok, checks = asar_api.verify_asar(asar)
            self.assertTrue(ok, checks)

            # Any missing marker fails verification
            for name, marker in asar_api.REQUIRED_MARKERS.items():
                others = b"\n".join(
                    m for n, m in asar_api.REQUIRED_MARKERS.items() if n != name
                )
                asar.write_bytes(others)
                ok, checks = asar_api.verify_asar(asar)
                self.assertFalse(ok, name)
                self.assertFalse(checks[name])

            # Stock cloud endpoints still present -> fail
            asar.write_bytes(full_payload + b"\n" + asar_api.STOCK_URLS[0])
            ok, checks = asar_api.verify_asar(asar)
            self.assertFalse(ok)
            self.assertFalse(checks["old Baseten gone"])

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
