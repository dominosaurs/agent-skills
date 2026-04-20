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
        self.assertTrue(all(op["mode"] == "merge" for op in ops))

    def test_validate_batch_operations_requires_approval(self) -> None:
        batch = {
            "operations": [
                {
                    "source_wing": "a",
                    "target_wing": "b",
                    "mode": "merge",
                    "risk": "medium",
                }
            ]
        }
        with self.assertRaises(SystemExit):
            partition_optimize.validate_batch_operations(batch, approve_merge=False)

    def test_validate_batch_operations_rejects_non_merge_mode(self) -> None:
        batch = {
            "operations": [
                {
                    "source_wing": "a",
                    "target_wing": "b",
                    "mode": "safe-merge",
                    "risk": "medium",
                }
            ]
        }
        with self.assertRaises(SystemExit):
            partition_optimize.validate_batch_operations(batch, approve_merge=True)

    def test_evaluate_tunnel_redundancy_trigger_detects_duplicate_intent(self) -> None:
        class FakeClient:
            def has_tool(self, name: str) -> bool:
                return name == "mempalace_list_tunnels"

            def call_tool(self, name: str, arguments: dict) -> list[dict]:
                _ = arguments
                self.assertEqual(name, "mempalace_list_tunnels")
                return [
                    {
                        "source_wing": "w1",
                        "source_room": "r1",
                        "target_wing": "w2",
                        "target_room": "r2",
                    },
                    {
                        "source_wing": "w1",
                        "source_room": "r1",
                        "target_wing": "w2",
                        "target_room": "r2",
                    },
                ]

            def assertEqual(self, left, right) -> None:
                if left != right:
                    raise AssertionError(f"{left!r} != {right!r}")

        result = partition_optimize.evaluate_tunnel_redundancy_trigger(FakeClient())
        self.assertTrue(result["evaluated"])
        self.assertTrue(result["triggered"])

    def test_evaluate_kg_conflict_trigger_detects_active_conflict(self) -> None:
        class FakeClient:
            def has_tool(self, name: str) -> bool:
                return name == "mempalace_kg_timeline"

            def call_tool(self, name: str, arguments: dict) -> list[dict]:
                _ = arguments
                if name != "mempalace_kg_timeline":
                    raise AssertionError(name)
                return [
                    {"subject": "ProjectX", "predicate": "owner", "object": "TeamA"},
                    {"subject": "ProjectX", "predicate": "owner", "object": "TeamB"},
                ]

        result = partition_optimize.evaluate_kg_conflict_trigger(FakeClient())
        self.assertTrue(result["evaluated"])
        self.assertTrue(result["triggered"])
        self.assertIn("ProjectX|owner", result["conflicts"])

    def test_evaluate_duplicate_trigger_requires_similarity_signal(self) -> None:
        class FakeClient:
            def has_tool(self, name: str) -> bool:
                return name == "mempalace_search"

            def call_tool(self, name: str, arguments: dict) -> list[dict]:
                _ = arguments
                if name != "mempalace_search":
                    raise AssertionError(name)
                return [
                    {"wing": "a", "content": "same text"},
                    {"wing": "b", "content": "same text"},
                ]

        result = partition_optimize.evaluate_duplicate_trigger(FakeClient(), ["x"])
        self.assertTrue(result["evaluated"])
        self.assertFalse(result["triggered"])

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

    def test_worth_score_threshold(self) -> None:
        self.assertEqual(partition_optimize.worth_score(2, 1, 0), 3)
        self.assertEqual(partition_optimize.worth_score(1, 1, 0), 2)

    def test_confidence_score_with_override(self) -> None:
        score = partition_optimize.confidence_score(
            confidence=0.2,
            source_count=1,
            contradiction_check="fail",
            user_confirmed=True,
            recency_days=0,
            duplicate_similarity=None,
        )
        self.assertEqual(score, 1.0)

    def test_budget_exceeded(self) -> None:
        pending = partition_optimize.default_pending_state()
        pending["usage"]["diary_writes"] = 1
        delta = {"diary_writes": 1, "kg_pairs": 0, "tunnel_actions": 0, "mcp_calls": 0}
        self.assertTrue(partition_optimize.budget_exceeded(pending, delta))

    def test_session_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = partition_optimize.session_paths(Path(tmp), "s1")
            self.assertTrue(str(paths["ledger"]).endswith("ledger-s1.jsonl"))
            self.assertTrue(str(paths["pending"]).endswith("pending-store-s1.json"))
            self.assertTrue(str(paths["flush"]).endswith("flush-report-s1.json"))

    def test_run_store_auto_milestone_skip_counts_mcp_calls_budget(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.tool_calls = 0

            def call_tool(self, name: str, arguments: dict) -> dict:
                self.tool_calls += 1
                _ = arguments
                if name == "mempalace_status":
                    return {"wings": {"w1": 1}}
                if name == "mempalace_check_duplicate":
                    return {"is_duplicate": False, "similarity": 0.1}
                raise AssertionError(name)

        with tempfile.TemporaryDirectory() as tmp:
            args = type(
                "Args",
                (),
                {
                    "session_id": "s1",
                    "checkpoint": "task_milestone",
                    "wing": "w1",
                    "room": "decisions",
                    "content_file": None,
                    "content": "short-lived note",
                    "durability": 0,
                    "reuse_impact": 0,
                    "uniqueness": 0,
                    "confidence": 0.1,
                    "source_count": 1,
                    "contradiction_check": "pass",
                    "recency_days": 0,
                    "sensitive": False,
                    "user_confirmed": False,
                    "user_instruction": False,
                    "kg_subject": None,
                    "kg_predicate": None,
                    "kg_object": None,
                    "tunnel_source_wing": None,
                    "tunnel_source_room": None,
                    "tunnel_target_wing": None,
                    "tunnel_target_room": None,
                    "tunnel_label": None,
                },
            )()
            code = partition_optimize.run_store_auto(FakeClient(), args, Path(tmp))
            self.assertEqual(code, 0)
            pending = json.loads((Path(tmp) / "pending-store-s1.json").read_text(encoding="utf-8"))
            self.assertEqual(pending["usage"]["mcp_calls"], 2)

    def test_run_flush_auto_compacts_and_dedupes_kg_tunnel(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def call_tool(self, name: str, arguments: dict):
                self.calls.append((name, arguments))
                if name == "mempalace_status":
                    return {"ok": True}
                if name == "mempalace_check_duplicate":
                    return {"is_duplicate": False, "similarity": 0.1}
                if name == "mempalace_add_drawer":
                    return {"ok": True}
                if name == "mempalace_kg_add":
                    return {"ok": True}
                if name == "mempalace_create_tunnel":
                    return {"ok": True}
                raise AssertionError(name)

        with tempfile.TemporaryDirectory() as tmp:
            pending_path = Path(tmp) / "pending-store-s1.json"
            pending_path.write_text(
                json.dumps(
                    {
                        "usage": {"diary_writes": 1, "kg_pairs": 1, "tunnel_actions": 1, "mcp_calls": 4},
                        "deferred": [
                            {
                                "wing": "w1",
                                "room": "r1",
                                "content": "alpha",
                                "kg_subject": "p",
                                "kg_predicate": "owns",
                                "kg_object": "x",
                                "tunnel_source_wing": "w1",
                                "tunnel_source_room": "r1",
                                "tunnel_target_wing": "w2",
                                "tunnel_target_room": "r2",
                                "confidence": 0.9,
                                "source_count": 2,
                                "contradiction_check": "pass",
                                "recency_days": 0,
                                "user_confirmed": False,
                                "user_instruction": False,
                            },
                            {
                                "wing": "w1",
                                "room": "r1",
                                "content": "beta",
                                "kg_subject": "p",
                                "kg_predicate": "owns",
                                "kg_object": "x",
                                "tunnel_source_wing": "w1",
                                "tunnel_source_room": "r1",
                                "tunnel_target_wing": "w2",
                                "tunnel_target_room": "r2",
                                "confidence": 0.95,
                                "source_count": 2,
                                "contradiction_check": "pass",
                                "recency_days": 0,
                                "user_confirmed": False,
                                "user_instruction": False,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {"session_id": "s1", "summary_wing": "sum", "summary_room": "diary"},
            )()
            client = FakeClient()
            code = partition_optimize.run_flush_auto(client, args, Path(tmp))
            self.assertEqual(code, 0)
            names = [name for name, _ in client.calls]
            self.assertEqual(names.count("mempalace_add_drawer"), 1)
            self.assertEqual(names.count("mempalace_kg_add"), 1)
            self.assertEqual(names.count("mempalace_create_tunnel"), 1)
            summary_payloads = [payload for name, payload in client.calls if name == "mempalace_add_drawer"]
            self.assertIn("DEFERRED:2", summary_payloads[0]["content"])


if __name__ == "__main__":
    unittest.main()
