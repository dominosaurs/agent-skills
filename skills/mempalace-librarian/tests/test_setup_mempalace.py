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
    def test_upsert_codex_mcp_preserves_other_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(
                'model = "gpt-5.4"\n\n[mcp_servers.other]\ncommand = "/bin/true"\n',
                encoding="utf-8",
            )

            setup_mempalace.upsert_codex_mcp(
                config,
                Path("/tmp/venv/bin/python"),
                None,
                dry_run=False,
            )

            text = config.read_text(encoding="utf-8")
            self.assertIn('[mcp_servers.other]', text)
            self.assertIn('[mcp_servers.mempalace]', text)
            self.assertIn('command = "/tmp/venv/bin/python"', text)
            self.assertIn('args = ["-m", "mempalace.mcp_server"]', text)

    def test_ensure_codex_hooks_dedupes_and_preserves_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hooks = Path(tmp) / "hooks.json"
            existing_command = setup_mempalace.hook_command(
                Path("/tmp/venv/bin/python"), "stop", "codex"
            )
            hooks.write_text(
                json.dumps(
                    {
                        "Stop": [
                            {"type": "command", "command": existing_command, "timeout": 30},
                            {"type": "command", "command": "/bin/other", "timeout": 10},
                        ],
                        "PreCompact": [],
                    }
                ),
                encoding="utf-8",
            )

            setup_mempalace.ensure_codex_hooks(
                hooks, Path("/tmp/venv/bin/python"), dry_run=False
            )

            data = json.loads(hooks.read_text(encoding="utf-8"))
            stop_cmds = [entry["command"] for entry in data["Stop"]]
            self.assertEqual(stop_cmds.count(existing_command), 1)
            self.assertIn("/bin/other", stop_cmds)
            pre_cmds = [entry["command"] for entry in data["PreCompact"]]
            self.assertEqual(
                pre_cmds,
                [setup_mempalace.hook_command(Path("/tmp/venv/bin/python"), "precompact", "codex")],
            )

    def test_ensure_codex_hooks_replaces_old_mempalace_python_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hooks = Path(tmp) / "hooks.json"
            hooks.write_text(
                json.dumps(
                    {
                        "Stop": [
                            {
                                "type": "command",
                                "command": "/old/python -m mempalace hook run --hook stop --harness codex",
                                "timeout": 30,
                            }
                        ],
                        "PreCompact": [
                            {
                                "type": "command",
                                "command": "/old/python -m mempalace hook run --hook precompact --harness codex",
                                "timeout": 30,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            setup_mempalace.ensure_codex_hooks(
                hooks, Path("/new/python"), dry_run=False
            )

            data = json.loads(hooks.read_text(encoding="utf-8"))
            self.assertEqual(len(data["Stop"]), 1)
            self.assertEqual(
                data["Stop"][0]["command"],
                "/new/python -m mempalace hook run --hook stop --harness codex",
            )
            self.assertEqual(len(data["PreCompact"]), 1)
            self.assertEqual(
                data["PreCompact"][0]["command"],
                "/new/python -m mempalace hook run --hook precompact --harness codex",
            )

    def test_ensure_claude_hooks_preserves_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.local.json"
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [
                                {
                                    "matcher": "*",
                                    "hooks": [
                                        {"type": "command", "command": "/bin/other", "timeout": 15}
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            setup_mempalace.ensure_claude_hooks(
                settings, Path("/tmp/venv/bin/python"), dry_run=False
            )

            data = json.loads(settings.read_text(encoding="utf-8"))
            stop_commands = [
                hook["command"]
                for entry in data["hooks"]["Stop"]
                for hook in entry.get("hooks", [])
            ]
            self.assertIn("/bin/other", stop_commands)
            self.assertIn(
                setup_mempalace.hook_command(
                    Path("/tmp/venv/bin/python"), "stop", "claude-code"
                ),
                stop_commands,
            )
            pre_commands = [
                hook["command"]
                for entry in data["hooks"]["PreCompact"]
                for hook in entry.get("hooks", [])
            ]
            self.assertIn(
                setup_mempalace.hook_command(
                    Path("/tmp/venv/bin/python"), "precompact", "claude-code"
                ),
                pre_commands,
            )

    def test_ensure_claude_hooks_replaces_old_mempalace_python_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.local.json"
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [
                                {
                                    "matcher": "*",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "/old/python -m mempalace hook run --hook stop --harness claude-code",
                                            "timeout": 30,
                                        }
                                    ],
                                }
                            ],
                            "PreCompact": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "/old/python -m mempalace hook run --hook precompact --harness claude-code",
                                            "timeout": 30,
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            setup_mempalace.ensure_claude_hooks(
                settings, Path("/new/python"), dry_run=False
            )

            data = json.loads(settings.read_text(encoding="utf-8"))
            stop_commands = [
                hook["command"]
                for entry in data["hooks"]["Stop"]
                for hook in entry.get("hooks", [])
            ]
            self.assertEqual(
                stop_commands,
                ["/new/python -m mempalace hook run --hook stop --harness claude-code"],
            )
            pre_commands = [
                hook["command"]
                for entry in data["hooks"]["PreCompact"]
                for hook in entry.get("hooks", [])
            ]
            self.assertEqual(
                pre_commands,
                ["/new/python -m mempalace hook run --hook precompact --harness claude-code"],
            )

    def test_ensure_gemini_settings_preserves_existing_and_writes_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = tmp_path / "settings.json"
            settings.write_text(
                json.dumps(
                    {
                        "ui": {"theme": "dark"},
                        "hooks": {
                            "PreCompress": [
                                {
                                    "matcher": "*",
                                    "hooks": [{"type": "command", "command": "/bin/other-hook"}],
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            repo = tmp_path / "repo"
            hook_dir = repo / "hooks"
            hook_dir.mkdir(parents=True)
            (hook_dir / "mempal_precompact_hook.sh").write_text("#!/bin/bash\n", encoding="utf-8")

            setup_mempalace.ensure_gemini_settings(
                settings,
                Path("/tmp/venv/bin/python"),
                None,
                repo,
                dry_run=False,
            )

            data = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(data["ui"]["theme"], "dark")
            self.assertEqual(
                data["mcpServers"]["mempalace"]["command"],
                "/tmp/venv/bin/python",
            )
            self.assertEqual(
                data["mcpServers"]["mempalace"]["args"],
                ["-m", "mempalace.mcp_server"],
            )
            commands = [
                hook["command"]
                for entry in data["hooks"]["PreCompress"]
                for hook in entry.get("hooks", [])
            ]
            self.assertIn("/bin/other-hook", commands)
            self.assertIn(str(hook_dir / "mempal_precompact_hook.sh"), commands)

    def test_ensure_gemini_settings_replaces_old_mempalace_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = tmp_path / "settings.json"
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreCompress": [
                                {
                                    "matcher": "*",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "/old/mempalace/hooks/mempal_precompact_hook.sh",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            repo = tmp_path / "repo"
            hook_dir = repo / "hooks"
            hook_dir.mkdir(parents=True)
            new_hook = hook_dir / "mempal_precompact_hook.sh"
            new_hook.write_text("#!/bin/bash\n", encoding="utf-8")

            setup_mempalace.ensure_gemini_settings(
                settings,
                Path("/tmp/venv/bin/python"),
                None,
                repo,
                dry_run=False,
            )

            data = json.loads(settings.read_text(encoding="utf-8"))
            commands = [
                hook["command"]
                for entry in data["hooks"]["PreCompress"]
                for hook in entry.get("hooks", [])
            ]
            self.assertEqual(commands, [str(new_hook)])

    def test_resolve_gemini_precompress_command_allows_dry_run_without_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = setup_mempalace.resolve_gemini_precompress_command(
                tmp_path / ".venv" / "bin" / "python",
                tmp_path / "missing-repo",
                dry_run=True,
            )
        self.assertTrue(command.endswith("/mempalace/hooks/mempal_precompact_hook.sh"))

    def test_verify_mcp_server_requires_status_tool(self) -> None:
        proc = mock.Mock()
        proc.stdin = mock.Mock()
        proc.stdout = mock.Mock()
        proc.stdout.readline.side_effect = [
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "mempalace"}}}
            )
            + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}) + "\n",
        ]
        proc.communicate.return_value = ("", "")

        with mock.patch.object(setup_mempalace.subprocess, "Popen", return_value=proc):
            with self.assertRaises(SystemExit):
                setup_mempalace.verify_mcp_server(
                    Path("/tmp/venv/bin/python"), None, dry_run=False
                )

    def test_configure_claude_mcp_requires_cli(self) -> None:
        with mock.patch.object(setup_mempalace.shutil, "which", return_value=None):
            with self.assertRaises(SystemExit):
                setup_mempalace.configure_claude_mcp(
                    Path("/tmp/venv/bin/python"), None, dry_run=False
                )

    def test_find_existing_mempalace_python_prefers_working_install(self) -> None:
        preferred = Path("/tmp/preferred")
        with mock.patch.object(
            setup_mempalace,
            "FALLBACK_EXISTING_VENV",
            Path("/tmp/fallback/bin/python"),
        ):
            with mock.patch.object(
                setup_mempalace,
                "has_mempalace",
                side_effect=lambda path: path == Path("/tmp/fallback/bin/python"),
            ):
                found = setup_mempalace.find_existing_mempalace_python(preferred)
        self.assertEqual(found, Path("/tmp/fallback/bin/python"))

    def test_find_existing_mempalace_python_prefers_configured_for_default_venv(self) -> None:
        configured = Path("/tmp/configured/bin/python")
        with mock.patch.object(setup_mempalace, "DEFAULT_VENV", Path("/tmp/default")):
            with mock.patch.object(
                setup_mempalace,
                "FALLBACK_EXISTING_VENV",
                Path("/tmp/fallback/bin/python"),
            ):
                with mock.patch.object(
                    setup_mempalace,
                    "has_mempalace",
                    side_effect=lambda path: path == configured,
                ):
                    found = setup_mempalace.find_existing_mempalace_python(
                        Path("/tmp/default"), [configured]
                    )
        self.assertEqual(found, configured)

    def test_find_existing_mempalace_python_prefers_explicit_venv(self) -> None:
        explicit = Path("/tmp/explicit")
        configured = Path("/tmp/configured/bin/python")
        with mock.patch.object(
            setup_mempalace,
            "has_mempalace",
            side_effect=lambda path: path == explicit / "bin" / "python",
        ):
            found = setup_mempalace.find_existing_mempalace_python(explicit, [configured])
        self.assertEqual(found, explicit / "bin" / "python")

    def test_configured_mcp_python_candidates_reads_codex_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(
                '[mcp_servers.mempalace]\n'
                f'command = "{tmp}/venv/bin/python"\n'
                'args = ["-m", "mempalace.mcp_server"]\n',
                encoding="utf-8",
            )
            with mock.patch.object(setup_mempalace, "CODEX_CONFIG", config):
                candidates = setup_mempalace.configured_mcp_python_candidates(["codex"])
        self.assertEqual(candidates, [Path(tmp) / "venv" / "bin" / "python"])

    def test_main_smoke_codex_with_temp_home_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            codex_dir = tmp_path / ".codex"
            codex_dir.mkdir()
            config_path = codex_dir / "config.toml"
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")

            args = mock.Mock(
                harness="codex",
                venv=str(tmp_path / ".mempalace" / "venv"),
                install_source="pypi",
                repo=str(tmp_path / "missing-repo"),
                palace=None,
                skip_hooks=False,
                dry_run=False,
            )

            with mock.patch.object(setup_mempalace, "parse_args", return_value=args):
                with mock.patch.object(setup_mempalace, "require_python", return_value="/usr/bin/python3"):
                    with mock.patch.object(
                        setup_mempalace, "find_existing_mempalace_python", return_value=None
                    ):
                        with mock.patch.object(
                            setup_mempalace,
                            "ensure_venv",
                            return_value=tmp_path / ".mempalace" / "venv" / "bin" / "python",
                        ):
                            with mock.patch.object(setup_mempalace, "install_mempalace"):
                                with mock.patch.object(setup_mempalace, "verify_cli"):
                                    with mock.patch.object(setup_mempalace, "verify_mcp_server"):
                                        with mock.patch.object(setup_mempalace, "CODEX_CONFIG", config_path):
                                            with mock.patch.object(
                                                setup_mempalace, "CODEX_HOOKS", codex_dir / "hooks.json"
                                            ):
                                                setup_mempalace.main()

            config_text = config_path.read_text(encoding="utf-8")
            self.assertIn("[mcp_servers.mempalace]", config_text)
            hooks_data = json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8"))
            self.assertIn("Stop", hooks_data)
            self.assertIn("PreCompact", hooks_data)

    def test_main_smoke_gemini_with_temp_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings_path = tmp_path / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            repo = tmp_path / "repo"
            hook_dir = repo / "hooks"
            hook_dir.mkdir(parents=True)
            (hook_dir / "mempal_precompact_hook.sh").write_text("#!/bin/bash\n", encoding="utf-8")

            args = mock.Mock(
                harness="gemini",
                venv=str(tmp_path / ".venv"),
                install_source="pypi",
                repo=str(repo),
                palace=None,
                skip_hooks=False,
                dry_run=False,
            )

            with mock.patch.object(setup_mempalace, "parse_args", return_value=args):
                with mock.patch.object(setup_mempalace, "require_python", return_value="/usr/bin/python3"):
                    with mock.patch.object(
                        setup_mempalace,
                        "find_existing_mempalace_python",
                        return_value=tmp_path / ".venv" / "bin" / "python",
                    ):
                        with mock.patch.object(setup_mempalace, "verify_cli"):
                            with mock.patch.object(setup_mempalace, "verify_mcp_server"):
                                with mock.patch.object(setup_mempalace, "GEMINI_SETTINGS", settings_path):
                                    setup_mempalace.main()

            data = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIn("mempalace", data["mcpServers"])
            self.assertIn("PreCompress", data["hooks"])


if __name__ == "__main__":
    unittest.main()
