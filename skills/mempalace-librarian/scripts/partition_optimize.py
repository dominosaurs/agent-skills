#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


HOME = Path.home()
CODEX_CONFIG = HOME / ".codex" / "config.toml"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.local.json"
GEMINI_SETTINGS = HOME / ".gemini" / "settings.json"
ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / ".artifacts" / "partition-optimization"
PROTOCOL_VERSION = "2025-03-26"

STATIC_BASELINE_QUERIES = [
    "architecture decisions",
    "project overview",
    "shared infra pattern",
    "cross wing linkage",
    "historical decision log",
]


@dataclass
class BatchOperation:
    source_wing: str
    target_wing: str
    mode: str
    risk: str


def now_utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def normalize_wing_name(name: str) -> str:
    value = name.lower().strip()
    value = re.sub(r"^[^a-z0-9]+", "", value)
    value = value.replace("_", "-")
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if value.startswith("wing-"):
        value = value[5:]
    return value


def detect_wing_collisions(wings: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for wing in wings:
        canonical = normalize_wing_name(wing)
        if not canonical:
            continue
        grouped.setdefault(canonical, []).append(wing)
    collisions = []
    for canonical, originals in grouped.items():
        unique = sorted(set(originals))
        if len(unique) < 2:
            continue
        collisions.append({"canonical": canonical, "wings": unique, "count": len(unique)})
    return sorted(collisions, key=lambda item: item["canonical"])


def build_dynamic_baseline_queries(status: dict[str, Any], max_dynamic: int = 10) -> list[str]:
    wings = status.get("wings", {})
    rooms = status.get("rooms", {})
    top_wings = sorted(wings.items(), key=lambda item: item[1], reverse=True)[:5]
    top_rooms = sorted(rooms.items(), key=lambda item: item[1], reverse=True)[:5]

    queries: list[str] = []
    for wing_name, _ in top_wings:
        candidate = normalize_wing_name(wing_name) or wing_name
        queries.append(candidate)
        if len(queries) >= max_dynamic:
            return queries
        queries.append(f"{candidate} architecture")
        if len(queries) >= max_dynamic:
            return queries
    for room_name, _ in top_rooms:
        queries.append(room_name)
        if len(queries) >= max_dynamic:
            break
    return queries[:max_dynamic]


def build_plan_from_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    collisions = diagnostic.get("symptoms", {}).get("wing_name_collisions", [])
    operations: list[BatchOperation] = []
    for collision in collisions:
        canonical = collision["canonical"]
        wings = collision["wings"]
        preferred_target = canonical if canonical in wings else canonical
        for source in wings:
            if source == preferred_target:
                continue
            risk = "high" if len(wings) > 2 else "medium"
            operations.append(
                BatchOperation(
                    source_wing=source,
                    target_wing=preferred_target,
                    mode="safe-merge",
                    risk=risk,
                )
            )

    batches: list[dict[str, Any]] = []
    current: list[BatchOperation] = []
    batch_idx = 1
    for op in operations:
        high_risk = any(item.risk == "high" for item in current)
        if len(current) >= 3 or (op.risk == "high" and current) or (high_risk and current):
            batches.append(
                {
                    "id": f"phase1-b{batch_idx}",
                    "phase": "phase1",
                    "operations": [item.__dict__ for item in current],
                }
            )
            batch_idx += 1
            current = []
        current.append(op)
    if current:
        batches.append(
            {
                "id": f"phase1-b{batch_idx}",
                "phase": "phase1",
                "operations": [item.__dict__ for item in current],
            }
        )
    return {"generated_at": now_utc_stamp(), "phase": "phase1", "batches": batches}


class MCPClient:
    def __init__(self, command: str, args: list[str]) -> None:
        self.command = command
        self.args = args
        self.proc: subprocess.Popen[str] | None = None
        self._req_id = 0

    def __enter__(self) -> MCPClient:
        self.proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}})
        tools = self._request("tools/list", {})
        names = {tool.get("name") for tool in tools.get("tools", [])}
        if "mempalace_status" not in names:
            raise SystemExit("MCP server missing mempalace_status tool")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.communicate(timeout=5)
        self.proc = None

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("MCP process not started")
        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params,
        }
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline().strip()
        if not line:
            raise SystemExit(f"MCP request failed: no response for {method}")
        response = json.loads(line)
        if "error" in response:
            raise SystemExit(f"MCP {method} error: {response['error']}")
        return response.get("result", {})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        if isinstance(content, list):
            for entry in content:
                if entry.get("type") != "text":
                    continue
                text = entry.get("text", "")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return result


def parse_mcp_server(server: dict[str, Any], source: str) -> tuple[str, list[str]]:
    command = server.get("command")
    args = server.get("args", [])
    if not isinstance(command, str) or not isinstance(args, list):
        raise SystemExit(f"Invalid mempalace MCP config in {source}")
    return command, [str(item) for item in args]


def load_codex_mcp_command() -> tuple[str, list[str]]:
    if tomllib is None:
        raise SystemExit("Python tomllib unavailable; cannot read Codex MCP config")
    if not CODEX_CONFIG.exists():
        raise SystemExit(f"Missing Codex config: {CODEX_CONFIG}")
    data = tomllib.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
    server = data.get("mcp_servers", {}).get("mempalace", {})
    return parse_mcp_server(server, f"Codex config ({CODEX_CONFIG})")


def load_claude_mcp_command() -> tuple[str, list[str]]:
    if not CLAUDE_SETTINGS.exists():
        raise SystemExit(f"Missing Claude settings: {CLAUDE_SETTINGS}")
    data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    server = data.get("mcpServers", {}).get("mempalace", {})
    return parse_mcp_server(server, f"Claude settings ({CLAUDE_SETTINGS})")


def load_gemini_mcp_command() -> tuple[str, list[str]]:
    if not GEMINI_SETTINGS.exists():
        raise SystemExit(f"Missing Gemini settings: {GEMINI_SETTINGS}")
    data = json.loads(GEMINI_SETTINGS.read_text(encoding="utf-8"))
    server = data.get("mcpServers", {}).get("mempalace", {})
    return parse_mcp_server(server, f"Gemini settings ({GEMINI_SETTINGS})")


def resolve_mcp_command(args: argparse.Namespace) -> tuple[str, list[str]]:
    if args.mcp_command:
        if args.mcp_arg:
            return args.mcp_command, list(args.mcp_arg)
        return args.mcp_command, ["-m", "mempalace.mcp_server"]

    if args.harness == "codex":
        return load_codex_mcp_command()
    if args.harness == "claude":
        return load_claude_mcp_command()
    if args.harness == "gemini":
        return load_gemini_mcp_command()

    errors: list[str] = []
    for name, loader in (
        ("codex", load_codex_mcp_command),
        ("claude", load_claude_mcp_command),
        ("gemini", load_gemini_mcp_command),
    ):
        try:
            return loader()
        except SystemExit as exc:
            errors.append(f"{name}: {exc}")
    raise SystemExit("Unable to resolve MemPalace MCP command in auto mode: " + "; ".join(errors))


def ensure_artifacts_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row) + "\n")


def latest_file(path: Path, prefix: str) -> Path | None:
    candidates = sorted(path.glob(f"{prefix}-*.json"), reverse=True)
    return candidates[0] if candidates else None


def parse_list_drawers_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("drawers", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def list_drawers_by_wing(client: MCPClient, wing: str, page_size: int = 100) -> list[dict[str, Any]]:
    offset = 0
    output: list[dict[str, Any]] = []
    while True:
        payload = client.call_tool(
            "mempalace_list_drawers",
            {"wing": wing, "limit": page_size, "offset": offset},
        )
        items = parse_list_drawers_payload(payload)
        if not items:
            break
        output.extend(items)
        if len(items) < page_size:
            break
        offset += len(items)
    return output


def run_analyze(client: MCPClient, artifacts_dir: Path) -> int:
    status = client.call_tool("mempalace_status", {})
    if not isinstance(status, dict):
        raise SystemExit("Invalid mempalace_status payload")
    wings = list((status.get("wings") or {}).keys())
    collisions = detect_wing_collisions(wings)
    static_queries = STATIC_BASELINE_QUERIES
    dynamic_queries = build_dynamic_baseline_queries(status)
    triggered = bool(collisions)
    diagnostic = {
        "generated_at": now_utc_stamp(),
        "command": "analyze",
        "symptoms": {
            "wing_name_collisions": collisions,
            "duplicate_hits": {"evaluated": False},
            "ambiguity": {"evaluated": False},
            "tunnel_redundancy": {"evaluated": False},
            "kg_conflict": {"evaluated": False},
        },
        "triggered": triggered,
        "queries": {"static": static_queries, "dynamic": dynamic_queries},
        "estimates": {"calls": {"low": 8, "high": 30}, "token_cost": "low-to-medium"},
    }
    out = artifacts_dir / f"diagnostic-{now_utc_stamp()}.json"
    write_json(out, diagnostic)
    if triggered:
        print("Optimization Suggested")
        print(f"Diagnostic: {out}")
        print(f"Phase candidate: phase1 (wing normalization), collisions={len(collisions)}")
    else:
        print("No optimization trigger detected")
        print(f"Diagnostic: {out}")
    return 0


def run_plan(diagnostic_path: Path, artifacts_dir: Path) -> int:
    if not diagnostic_path.exists():
        raise SystemExit(f"Missing diagnostic file: {diagnostic_path}")
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    plan = {
        "generated_at": now_utc_stamp(),
        "from_diagnostic": str(diagnostic_path),
        **build_plan_from_diagnostic(diagnostic),
    }
    out = artifacts_dir / f"plan-{now_utc_stamp()}.json"
    write_json(out, plan)
    print(f"Plan: {out}")
    print(f"Batches: {len(plan.get('batches', []))}")
    return 0


def find_batch(plan: dict[str, Any], phase: str, batch_id: str) -> dict[str, Any]:
    for batch in plan.get("batches", []):
        if batch.get("phase") == phase and batch.get("id") == batch_id:
            return batch
    raise SystemExit(f"Batch not found: phase={phase} id={batch_id}")


def run_regression_checks(client: MCPClient, target_wings: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "checks": []}
    try:
        client.call_tool("mempalace_status", {})
        result["checks"].append({"name": "status", "ok": True})
    except Exception as exc:  # pragma: no cover
        result["checks"].append({"name": "status", "ok": False, "error": str(exc)})
        result["ok"] = False
        return result

    for wing in sorted(set(target_wings)):
        try:
            payload = client.call_tool("mempalace_list_drawers", {"wing": wing, "limit": 1, "offset": 0})
            ok = isinstance(payload, (dict, list, str))
            result["checks"].append({"name": f"list_drawers:{wing}", "ok": ok})
            if not ok:
                result["ok"] = False
        except Exception as exc:  # pragma: no cover
            result["checks"].append({"name": f"list_drawers:{wing}", "ok": False, "error": str(exc)})
            result["ok"] = False
    return result


def run_execute(
    client: MCPClient,
    phase: str,
    batch_id: str,
    plan_path: Path,
    artifacts_dir: Path,
) -> int:
    if not plan_path.exists():
        raise SystemExit(f"Missing plan file: {plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    batch = find_batch(plan, phase, batch_id)
    timestamp = now_utc_stamp()
    batch_log = artifacts_dir / f"batch-{timestamp}-{batch_id}.jsonl"
    rollback_log = artifacts_dir / f"rollback-{timestamp}-{batch_id}.json"
    regression_log = artifacts_dir / f"regression-{timestamp}-{batch_id}.json"

    mutations: list[dict[str, Any]] = []
    target_wings: list[str] = []
    for op in batch.get("operations", []):
        source = op["source_wing"]
        target = op["target_wing"]
        target_wings.append(target)
        drawers = list_drawers_by_wing(client, source)
        for drawer in drawers:
            drawer_id = drawer.get("id") or drawer.get("drawer_id")
            if not drawer_id:
                continue
            client.call_tool("mempalace_update_drawer", {"drawer_id": drawer_id, "wing": target})
            mutations.append(
                {
                    "action": "move_drawer",
                    "drawer_id": drawer_id,
                    "from_wing": source,
                    "to_wing": target,
                }
            )

    append_jsonl(batch_log, mutations)
    write_json(
        rollback_log,
        {
            "generated_at": timestamp,
            "phase": phase,
            "batch_id": batch_id,
            "entries": mutations,
        },
    )
    regression = run_regression_checks(client, target_wings)
    write_json(regression_log, regression)

    if not regression.get("ok", False):
        for entry in reversed(mutations):
            client.call_tool(
                "mempalace_update_drawer",
                {"drawer_id": entry["drawer_id"], "wing": entry["from_wing"]},
            )
        write_json(
            rollback_log,
            {
                "generated_at": timestamp,
                "phase": phase,
                "batch_id": batch_id,
                "rolled_back": True,
                "entries": mutations,
            },
        )
        raise SystemExit("Regression checks failed; batch rolled back")

    print(f"Executed batch {batch_id}")
    print(f"Mutation log: {batch_log}")
    print(f"Regression log: {regression_log}")
    return 0


def latest_batch_log_for_id(artifacts_dir: Path, batch_id: str) -> Path | None:
    candidates = sorted(artifacts_dir.glob(f"batch-*-{batch_id}.jsonl"), reverse=True)
    return candidates[0] if candidates else None


def run_rollback(client: MCPClient, batch_id: str, batch_log: Path | None, artifacts_dir: Path) -> int:
    log_path = batch_log or latest_batch_log_for_id(artifacts_dir, batch_id)
    if log_path is None or not log_path.exists():
        raise SystemExit(f"No batch log found for batch id: {batch_id}")
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for entry in reversed(entries):
        client.call_tool(
            "mempalace_update_drawer",
            {"drawer_id": entry["drawer_id"], "wing": entry["from_wing"]},
        )
    out = artifacts_dir / f"rollback-{now_utc_stamp()}-{batch_id}.json"
    write_json(out, {"rolled_back_from": str(log_path), "entries": entries})
    print(f"Rolled back batch {batch_id}")
    print(f"Rollback record: {out}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge Partitioning Optimization CLI")
    parser.add_argument("--artifacts-dir", default=str(ARTIFACTS_DIR))
    parser.add_argument(
        "--harness",
        choices=["auto", "codex", "claude", "gemini"],
        default="auto",
        help="Where to resolve mempalace MCP command from.",
    )
    parser.add_argument(
        "--mcp-command",
        help="Explicit MCP server command override (agent-agnostic).",
    )
    parser.add_argument(
        "--mcp-arg",
        action="append",
        default=[],
        help="Repeatable MCP command arg; use multiple times for full arg list.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("analyze")

    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--diagnostic")

    exec_parser = sub.add_parser("execute")
    exec_parser.add_argument("phase")
    exec_parser.add_argument("batch_id")
    exec_parser.add_argument("--plan", required=True)

    rollback_parser = sub.add_parser("rollback")
    rollback_parser.add_argument("batch_id")
    rollback_parser.add_argument("--batch-log")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifacts_dir = ensure_artifacts_dir(Path(args.artifacts_dir))

    if args.command == "plan":
        diagnostic = Path(args.diagnostic) if args.diagnostic else latest_file(artifacts_dir, "diagnostic")
        if diagnostic is None:
            raise SystemExit("No diagnostic file found. Run analyze first.")
        return run_plan(diagnostic, artifacts_dir)

    command, mcp_args = resolve_mcp_command(args)
    with MCPClient(command, mcp_args) as client:
        if args.command == "analyze":
            return run_analyze(client, artifacts_dir)
        if args.command == "execute":
            return run_execute(client, args.phase, args.batch_id, Path(args.plan), artifacts_dir)
        if args.command == "rollback":
            batch_log = Path(args.batch_log) if args.batch_log else None
            return run_rollback(client, args.batch_id, batch_log, artifacts_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
