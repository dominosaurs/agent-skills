from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "setup_mempalace.py"
SPEC = importlib.util.spec_from_file_location("setup_mempalace", MODULE_PATH)
setup_mempalace = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(setup_mempalace)


class SetupMempalaceTests(unittest.TestCase):
    def test_dedicated_venv_path_uses_xdg_when_set(self) -> None:
        with mock.patch.dict(setup_mempalace.os.environ, {"XDG_DATA_HOME": "/tmp/xdg"}):
            self.assertEqual(
                setup_mempalace.dedicated_venv_path(),
                Path("/tmp/xdg/mempalace-librarian/venv"),
            )

    def test_dedicated_venv_path_falls_back_to_local_share(self) -> None:
        with mock.patch.dict(setup_mempalace.os.environ, {}, clear=True):
            with mock.patch.object(setup_mempalace, "HOME", Path("/tmp/home")):
                self.assertEqual(
                    setup_mempalace.dedicated_venv_path(),
                    Path("/tmp/home/.local/share/mempalace-librarian/venv"),
                )

    def test_ensure_dedicated_runtime_creates_when_missing(self) -> None:
        venv = Path("/tmp/new-venv")
        with mock.patch.object(Path, "exists", return_value=False):
            with mock.patch.object(
                setup_mempalace, "ensure_venv", return_value=venv / "bin" / "python"
            ) as ensure_venv:
                with mock.patch.object(setup_mempalace, "install_mempalace") as install:
                    out = setup_mempalace.ensure_dedicated_runtime(
                        venv=venv,
                        python_bin="/usr/bin/python3",
                        install_args=["mempalace"],
                        dry_run=False,
                    )
        self.assertEqual(out, venv / "bin" / "python")
        ensure_venv.assert_called_once()
        install.assert_called_once()

    def test_ensure_dedicated_runtime_fails_when_existing_python_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            venv.mkdir(parents=True)
            with self.assertRaises(SystemExit) as ctx:
                setup_mempalace.ensure_dedicated_runtime(
                    venv=venv,
                    python_bin="/usr/bin/python3",
                    install_args=["mempalace"],
                    dry_run=False,
                )
        self.assertEqual(ctx.exception.code, setup_mempalace.BROKEN_VENV_EXIT)

    def test_ensure_dedicated_runtime_fails_when_existing_runtime_checks_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            bin_dir = venv / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").write_text("", encoding="utf-8")
            with mock.patch.object(setup_mempalace, "verify_cli", return_value=False):
                with mock.patch.object(setup_mempalace, "verify_imports", return_value=True):
                    with self.assertRaises(SystemExit) as ctx:
                        setup_mempalace.ensure_dedicated_runtime(
                            venv=venv,
                            python_bin="/usr/bin/python3",
                            install_args=["mempalace"],
                            dry_run=False,
                        )
        self.assertEqual(ctx.exception.code, setup_mempalace.BROKEN_VENV_EXIT)

    def test_render_codex_mcp_config_preserves_other_sections(self) -> None:
        existing = 'model = "gpt-5.4"\n\n[mcp_servers.other]\ncommand = "/bin/true"\n'
        rendered = setup_mempalace.render_codex_mcp_config(
            existing,
            Path("/tmp/venv/bin/python"),
            None,
        )
        self.assertIn('[mcp_servers.other]', rendered)
        self.assertIn('[mcp_servers.mempalace]', rendered)
        self.assertIn('command = "/tmp/venv/bin/python"', rendered)

    def test_claude_settings_payload_writes_mcp_without_hooks_when_skipped(self) -> None:
        data = {"user": {"theme": "dark"}}
        out = setup_mempalace.claude_settings_payload(
            data,
            Path("/tmp/venv/bin/python"),
            None,
            include_hooks=False,
        )
        self.assertEqual(out["user"]["theme"], "dark")
        self.assertEqual(out["mcpServers"]["mempalace"]["command"], "/tmp/venv/bin/python")
        self.assertNotIn("hooks", out)

    def test_gemini_settings_payload_replaces_old_mempalace_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            hook_dir = repo / "hooks"
            hook_dir.mkdir(parents=True)
            hook = hook_dir / "mempal_precompact_hook.sh"
            hook.write_text("#!/bin/bash\n", encoding="utf-8")
            data = {
                "hooks": {
                    "PreCompress": [
                        {
                            "matcher": "*",
                            "hooks": [{"type": "command", "command": "/old/mempal_precompact_hook.sh"}],
                        }
                    ]
                }
            }
            out = setup_mempalace.gemini_settings_payload(
                data,
                Path("/tmp/venv/bin/python"),
                None,
                repo,
                include_hooks=True,
                dry_run=False,
            )
        commands = [
            hook_item["command"]
            for entry in out["hooks"]["PreCompress"]
            for hook_item in entry.get("hooks", [])
        ]
        self.assertEqual(commands, [str(hook)])

    def test_main_writes_all_three_harnesses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            hook_dir = repo / "hooks"
            hook_dir.mkdir(parents=True)
            (hook_dir / "mempal_precompact_hook.sh").write_text("#!/bin/bash\n", encoding="utf-8")

            args = mock.Mock(
                install_source="pypi",
                repo=str(repo),
                palace=None,
                skip_hooks=False,
                dry_run=False,
            )
            venv_python = tmp_path / "venv" / "bin" / "python"
            codex_config = tmp_path / "config.toml"
            codex_hooks = tmp_path / "hooks.json"
            claude_settings = tmp_path / "settings.local.json"
            gemini_settings = tmp_path / "settings.json"

            with mock.patch.object(setup_mempalace, "parse_args", return_value=args):
                with mock.patch.object(setup_mempalace, "require_python", return_value="/usr/bin/python3"):
                    with mock.patch.object(setup_mempalace, "dedicated_venv_path", return_value=tmp_path / "venv"):
                        with mock.patch.object(
                            setup_mempalace,
                            "ensure_dedicated_runtime",
                            return_value=venv_python,
                        ):
                            with mock.patch.object(setup_mempalace, "verify_cli", return_value=True):
                                with mock.patch.object(setup_mempalace, "verify_imports", return_value=True):
                                    with mock.patch.object(setup_mempalace, "verify_mcp_server", return_value=True):
                                        with mock.patch.object(setup_mempalace, "CODEX_CONFIG", codex_config):
                                            with mock.patch.object(setup_mempalace, "CODEX_HOOKS", codex_hooks):
                                                with mock.patch.object(
                                                    setup_mempalace, "CLAUDE_SETTINGS", claude_settings
                                                ):
                                                    with mock.patch.object(
                                                        setup_mempalace, "GEMINI_SETTINGS", gemini_settings
                                                    ):
                                                        setup_mempalace.main()

            self.assertIn("[mcp_servers.mempalace]", codex_config.read_text(encoding="utf-8"))
            self.assertIn("Stop", json.loads(codex_hooks.read_text(encoding="utf-8")))
            self.assertIn("mcpServers", json.loads(claude_settings.read_text(encoding="utf-8")))
            self.assertIn("mcpServers", json.loads(gemini_settings.read_text(encoding="utf-8")))

    def test_main_stops_on_broken_runtime_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            args = mock.Mock(
                install_source="pypi",
                repo=str(tmp_path / "repo"),
                palace=None,
                skip_hooks=False,
                dry_run=False,
            )
            codex_config = tmp_path / "config.toml"
            codex_config.write_text('model = "gpt-5.4"\n', encoding="utf-8")

            with mock.patch.object(setup_mempalace, "parse_args", return_value=args):
                with mock.patch.object(setup_mempalace, "require_python", return_value="/usr/bin/python3"):
                    with mock.patch.object(
                        setup_mempalace,
                        "ensure_dedicated_runtime",
                        side_effect=SystemExit(setup_mempalace.BROKEN_VENV_EXIT),
                    ):
                        with mock.patch.object(setup_mempalace, "CODEX_CONFIG", codex_config):
                            with self.assertRaises(SystemExit) as ctx:
                                setup_mempalace.main()
            self.assertEqual(ctx.exception.code, setup_mempalace.BROKEN_VENV_EXIT)
            self.assertEqual(codex_config.read_text(encoding="utf-8"), 'model = "gpt-5.4"\n')


if __name__ == "__main__":
    unittest.main()
