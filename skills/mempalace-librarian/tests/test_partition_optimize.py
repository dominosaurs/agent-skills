from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "partition_optimize.py"
SPEC = importlib.util.spec_from_file_location("partition_optimize", MODULE_PATH)
partition_optimize = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = partition_optimize
assert SPEC.loader is not None
SPEC.loader.exec_module(partition_optimize)


class PartitionOptimizeTests(unittest.TestCase):
    def test_normalize_wing_name(self) -> None:
        self.assertEqual(partition_optimize.normalize_wing_name(".gemini"), "gemini")
        self.assertEqual(partition_optimize.normalize_wing_name("wing_gemini_cli"), "gemini-cli")
        self.assertEqual(partition_optimize.normalize_wing_name("agent_skills"), "agent-skills")

    def test_detect_wing_collisions(self) -> None:
        collisions = partition_optimize.detect_wing_collisions(
            [".gemini", "gemini", "wing_gemini_cli", "wing_gemini-cli", "agent-skills"]
        )
        keys = {item["canonical"] for item in collisions}
        self.assertIn("gemini", keys)
        self.assertIn("gemini-cli", keys)

    def test_build_dynamic_baseline_queries_respects_cap(self) -> None:
        status = {
            "wings": {"a": 10, "b": 9, "c": 8, "d": 7, "e": 6},
            "rooms": {"r1": 10, "r2": 9, "r3": 8},
        }
        queries = partition_optimize.build_dynamic_baseline_queries(status, max_dynamic=10)
        self.assertLessEqual(len(queries), 10)

    def test_build_plan_from_diagnostic_batches(self) -> None:
        diagnostic = {
            "symptoms": {
                "wing_name_collisions": [
                    {"canonical": "gemini", "wings": [".gemini", "gemini"], "count": 2},
                    {
                        "canonical": "gemini-cli",
                        "wings": ["wing_gemini_cli", "wing_gemini-cli", "gemini-cli"],
                        "count": 3,
                    },
                ]
            }
        }
        plan = partition_optimize.build_plan_from_diagnostic(diagnostic)
        self.assertEqual(plan["phase"], "phase1")
        self.assertGreaterEqual(len(plan["batches"]), 1)
        ops = [op for batch in plan["batches"] for op in batch["operations"]]
        self.assertTrue(any(op["source_wing"] == ".gemini" and op["target_wing"] == "gemini" for op in ops))

    def test_resolve_mcp_command_with_explicit_override(self) -> None:
        args = type(
            "Args",
            (),
            {
                "harness": "auto",
                "mcp_command": "/usr/bin/python3",
                "mcp_arg": ["-m", "mempalace.mcp_server"],
            },
        )()
        command, argv = partition_optimize.resolve_mcp_command(args)
        self.assertEqual(command, "/usr/bin/python3")
        self.assertEqual(argv, ["-m", "mempalace.mcp_server"])

    def test_resolve_mcp_command_auto_uses_claude_when_codex_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            claude_settings = tmp_path / "settings.local.json"
            claude_settings.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "mempalace": {
                                "command": "/usr/bin/python3",
                                "args": ["-m", "mempalace.mcp_server"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {"harness": "auto", "mcp_command": None, "mcp_arg": []},
            )()
            original_codex = partition_optimize.CODEX_CONFIG
            original_claude = partition_optimize.CLAUDE_SETTINGS
            original_gemini = partition_optimize.GEMINI_SETTINGS
            try:
                partition_optimize.CODEX_CONFIG = tmp_path / "missing.toml"
                partition_optimize.CLAUDE_SETTINGS = claude_settings
                partition_optimize.GEMINI_SETTINGS = tmp_path / "missing-gemini.json"
                command, argv = partition_optimize.resolve_mcp_command(args)
            finally:
                partition_optimize.CODEX_CONFIG = original_codex
                partition_optimize.CLAUDE_SETTINGS = original_claude
                partition_optimize.GEMINI_SETTINGS = original_gemini
            self.assertEqual(command, "/usr/bin/python3")
            self.assertEqual(argv, ["-m", "mempalace.mcp_server"])


if __name__ == "__main__":
    unittest.main()
