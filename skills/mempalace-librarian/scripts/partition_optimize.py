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
AUTO_STORE_DIR = Path(__file__).resolve().parents[1] / ".artifacts" / "auto-store"
PROTOCOL_VERSION = "2025-03-26"
DUPLICATE_THRESHOLD = 0.92

REASON_STORED_OK = "STORED_OK"
REASON_NOVELTY_LOW = "NOVELTY_LOW"
REASON_DUPLICATE_HIGH = "DUPLICATE_HIGH"
REASON_CONFIDENCE_LOW = "CONFIDENCE_LOW"
REASON_BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
REASON_SENSITIVE_REDACTED = "SENSITIVE_REDACTED"
REASON_LIFECYCLE_READ_ONLY = "LIFECYCLE_READ_ONLY"

STATIC_BASELINE_QUERIES = [
    "architecture decisions",
    "project overview",
    "shared infra pattern",
    "cross wing linkage",
    "historical decision log",
]

MILESTONE_BUDGET = {
    "diary_writes": 1,
    "kg_pairs": 1,
    "tunnel_actions": 1,
    "mcp_calls": 8,
}


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
                    mode="merge",
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
        self.tool_calls = 0
        self.tool_names: set[str] = set()

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
        self.tool_names = {name for name in names if isinstance(name, str)}
        if "mempalace_status" not in self.tool_names:
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
        self.tool_calls += 1
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

    def has_tool(self, name: str) -> bool:
        return name in self.tool_names


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


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def session_paths(artifacts_dir: Path, session_id: str) -> dict[str, Path]:
    return {
        "ledger": artifacts_dir / f"ledger-{session_id}.jsonl",
        "pending": artifacts_dir / f"pending-store-{session_id}.json",
        "flush": artifacts_dir / f"flush-report-{session_id}.json",
    }


def worth_score(durability: int, reuse_impact: int, uniqueness: int) -> int:
    return durability + reuse_impact + uniqueness


def confidence_score(
    confidence: float,
    source_count: int,
    contradiction_check: str,
    user_confirmed: bool,
    recency_days: int,
    duplicate_similarity: float | None,
) -> float:
    if user_confirmed:
        return 1.0
    score = confidence
    if source_count >= 2:
        score += 0.05
    if contradiction_check == "fail":
        score -= 0.25
    if recency_days > 30:
        score -= 0.05
    if duplicate_similarity is not None and duplicate_similarity >= DUPLICATE_THRESHOLD:
        score -= 0.15
    return max(0.0, min(1.0, score))


def normalize_duplicate_similarity(payload: Any) -> tuple[bool, float | None]:
    if isinstance(payload, dict):
        if isinstance(payload.get("is_duplicate"), bool):
            sim = payload.get("similarity")
            return payload["is_duplicate"], float(sim) if isinstance(sim, (int, float)) else None
        sim = payload.get("similarity")
        if isinstance(sim, (int, float)):
            return sim >= DUPLICATE_THRESHOLD, float(sim)
        if isinstance(payload.get("matches"), list) and payload["matches"]:
            first = payload["matches"][0]
            if isinstance(first, dict):
                score = first.get("similarity")
                if isinstance(score, (int, float)):
                    return score >= DUPLICATE_THRESHOLD, float(score)
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            score = first.get("similarity")
            if isinstance(score, (int, float)):
                return score >= DUPLICATE_THRESHOLD, float(score)
    return False, None


def redact_content(content: str) -> str:
    text = content
    text = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]", text)
    text = re.sub(r"(?i)bearer\s+[a-z0-9\-\._~\+\/]+=*", "Bearer [REDACTED_TOKEN]", text)
    text = re.sub(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]", text)
    return text


def default_pending_state() -> dict[str, Any]:
    return {
        "usage": {"diary_writes": 0, "kg_pairs": 0, "tunnel_actions": 0, "mcp_calls": 0},
        "deferred": [],
    }


def budget_exceeded(pending: dict[str, Any], delta: dict[str, int]) -> bool:
    usage = pending.get("usage", {})
    for key, add in delta.items():
        if usage.get(key, 0) + add > MILESTONE_BUDGET[key]:
            return True
    return False


def apply_budget(pending: dict[str, Any], delta: dict[str, int]) -> None:
    usage = pending.setdefault("usage", {})
    for key, add in delta.items():
        usage[key] = usage.get(key, 0) + add


def ledger_row(
    session_id: str,
    checkpoint: str,
    reason: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "timestamp": now_utc_stamp(),
        "session_id": session_id,
        "checkpoint": checkpoint,
        "reason": reason,
        "payload": payload,
    }

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


def parse_search_hits(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "items", "matches", "drawers"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def parse_tunnels_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("tunnels", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def parse_kg_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("timeline", "facts", "triples", "rows", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def hit_wing(hit: dict[str, Any]) -> str | None:
    for key in ("wing", "source_wing", "project"):
        value = hit.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    meta = hit.get("metadata")
    if isinstance(meta, dict):
        value = meta.get("wing")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def hit_similarity(hit: dict[str, Any]) -> float | None:
    for key in ("similarity", "score"):
        value = hit.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    distance = hit.get("distance")
    if isinstance(distance, (int, float)):
        return max(0.0, 1.0 - float(distance))
    return None


def hit_fingerprint(hit: dict[str, Any]) -> str:
    for key in ("content", "preview", "snippet", "text", "title", "name"):
        value = hit.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = re.sub(r"\s+", " ", value.strip().lower())
            return cleaned[:160]
    drawer_id = hit.get("id") or hit.get("drawer_id")
    if isinstance(drawer_id, str):
        return drawer_id
    return ""


def query_search(client: MCPClient, query: str, wing: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    arguments: dict[str, Any] = {"query": query, "limit": limit}
    if wing:
        arguments["wing"] = wing
    payload = client.call_tool("mempalace_search", arguments)
    return parse_search_hits(payload)


def evaluate_duplicate_trigger(client: MCPClient, queries: list[str]) -> dict[str, Any]:
    if not client.has_tool("mempalace_search"):
        return {"evaluated": False, "triggered": False, "reason": "mempalace_search unavailable"}
    evaluated_queries = 0
    for query in queries:
        hits = query_search(client, query, limit=10)
        if not hits:
            continue
        evaluated_queries += 1
        grouped: dict[str, list[dict[str, Any]]] = {}
        for hit in hits:
            fp = hit_fingerprint(hit)
            if not fp:
                continue
            grouped.setdefault(fp, []).append(hit)
        duplicate_hits = 0
        for group in grouped.values():
            wings = {hit_wing(item) for item in group if hit_wing(item)}
            if len(group) < 2 or len(wings) < 2:
                continue
            scores = [score for score in (hit_similarity(item) for item in group) if score is not None]
            if scores and any(score >= DUPLICATE_THRESHOLD for score in scores):
                duplicate_hits += len(group)
        ratio = duplicate_hits / len(hits)
        if ratio >= 0.30:
            return {
                "evaluated": True,
                "triggered": True,
                "query": query,
                "ratio": round(ratio, 3),
                "hits": len(hits),
            }
        if evaluated_queries >= 10:
            break
    return {"evaluated": evaluated_queries > 0, "triggered": False, "queries_checked": evaluated_queries}


def evaluate_ambiguity_trigger(client: MCPClient, status: dict[str, Any]) -> dict[str, Any]:
    if not client.has_tool("mempalace_search"):
        return {"evaluated": False, "triggered": False, "reason": "mempalace_search unavailable"}
    wings = status.get("wings", {})
    if not isinstance(wings, dict) or not wings:
        return {"evaluated": False, "triggered": False, "reason": "no wings"}
    top_wings = [name for name, _ in sorted(wings.items(), key=lambda item: item[1], reverse=True)[:3]]
    checked = 0
    for wing in top_wings:
        query = f"{normalize_wing_name(wing) or wing} project overview"
        hits = query_search(client, query, limit=10)
        checked += 1
        scope_wings = {hit_wing(hit) for hit in hits if hit_wing(hit)}
        if len(scope_wings) >= 3:
            return {
                "evaluated": True,
                "triggered": True,
                "query": query,
                "wing_count": len(scope_wings),
                "wings": sorted(scope_wings),
            }
    return {"evaluated": checked > 0, "triggered": False, "queries_checked": checked}


def evaluate_tunnel_redundancy_trigger(client: MCPClient) -> dict[str, Any]:
    if not client.has_tool("mempalace_list_tunnels"):
        return {"evaluated": False, "triggered": False, "reason": "mempalace_list_tunnels unavailable"}
    payload = client.call_tool("mempalace_list_tunnels", {})
    tunnels = parse_tunnels_payload(payload)
    intents: dict[str, int] = {}
    for tunnel in tunnels:
        src_wing = str(tunnel.get("source_wing", "")).strip()
        src_room = str(tunnel.get("source_room", "")).strip()
        dst_wing = str(tunnel.get("target_wing", "")).strip()
        dst_room = str(tunnel.get("target_room", "")).strip()
        key = "->".join([src_wing, src_room, dst_wing, dst_room])
        intents[key] = intents.get(key, 0) + 1
    redundant = {key: count for key, count in intents.items() if count >= 2}
    return {
        "evaluated": True,
        "triggered": bool(redundant),
        "redundant_intents": redundant,
        "tunnel_count": len(tunnels),
    }


def _kg_is_active(row: dict[str, Any]) -> bool:
    for key in ("ended", "valid_to", "invalidated_at"):
        value = row.get(key)
        if value not in (None, ""):
            return False
    return True


def evaluate_kg_conflict_trigger(client: MCPClient) -> dict[str, Any]:
    if not client.has_tool("mempalace_kg_timeline"):
        return {"evaluated": False, "triggered": False, "reason": "mempalace_kg_timeline unavailable"}
    payload = client.call_tool("mempalace_kg_timeline", {})
    rows = parse_kg_rows(payload)
    active: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        subject = row.get("subject")
        predicate = row.get("predicate")
        obj = row.get("object")
        if not isinstance(subject, str) or not isinstance(predicate, str) or not isinstance(obj, str):
            continue
        if not _kg_is_active(row):
            continue
        key = (subject, predicate)
        active.setdefault(key, set()).add(obj)
    conflicts = {
        f"{subject}|{predicate}": sorted(values)
        for (subject, predicate), values in active.items()
        if len(values) > 1
    }
    return {
        "evaluated": True,
        "triggered": bool(conflicts),
        "conflicts": conflicts,
    }


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
    baseline_queries = static_queries + dynamic_queries[:5]
    duplicate_hits = evaluate_duplicate_trigger(client, baseline_queries)
    ambiguity = evaluate_ambiguity_trigger(client, status)
    tunnel_redundancy = evaluate_tunnel_redundancy_trigger(client)
    kg_conflict = evaluate_kg_conflict_trigger(client)
    triggered = any(
        [
            bool(collisions),
            duplicate_hits.get("triggered", False),
            ambiguity.get("triggered", False),
            tunnel_redundancy.get("triggered", False),
            kg_conflict.get("triggered", False),
        ]
    )
    diagnostic = {
        "generated_at": now_utc_stamp(),
        "command": "analyze",
        "symptoms": {
            "wing_name_collisions": collisions,
            "duplicate_hits": duplicate_hits,
            "ambiguity": ambiguity,
            "tunnel_redundancy": tunnel_redundancy,
            "kg_conflict": kg_conflict,
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


def run_regression_checks(
    client: MCPClient,
    source_wings: list[str],
    target_wings: list[str],
    check_tunnels: bool,
    check_kg: bool,
) -> dict[str, Any]:
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
    for wing in sorted(set(source_wings)):
        try:
            payload = client.call_tool("mempalace_list_drawers", {"wing": wing, "limit": 1, "offset": 0})
            remaining = parse_list_drawers_payload(payload)
            ok = len(remaining) == 0
            result["checks"].append({"name": f"source_empty:{wing}", "ok": ok, "remaining": len(remaining)})
            if not ok:
                result["ok"] = False
        except Exception as exc:  # pragma: no cover
            result["checks"].append({"name": f"source_empty:{wing}", "ok": False, "error": str(exc)})
            result["ok"] = False
    if client.has_tool("mempalace_search"):
        for wing in sorted(set(target_wings)):
            try:
                hits = query_search(client, f"{wing} architecture", wing=wing, limit=10)
                result["checks"].append({"name": f"search_precision:{wing}", "ok": isinstance(hits, list), "hits": len(hits)})
            except Exception as exc:  # pragma: no cover
                result["checks"].append({"name": f"search_precision:{wing}", "ok": False, "error": str(exc)})
                result["ok"] = False
            try:
                hits = query_search(client, f"{wing} project overview", limit=10)
                wings = sorted({hit_wing(hit) for hit in hits if hit_wing(hit)})
                ok = len(wings) <= 3
                result["checks"].append({"name": f"search_ambiguity:{wing}", "ok": ok, "wings": wings})
                if not ok:
                    result["ok"] = False
            except Exception as exc:  # pragma: no cover
                result["checks"].append({"name": f"search_ambiguity:{wing}", "ok": False, "error": str(exc)})
                result["ok"] = False
    if check_tunnels and client.has_tool("mempalace_list_tunnels"):
        try:
            payload = client.call_tool("mempalace_list_tunnels", {})
            ok = isinstance(payload, (dict, list))
            result["checks"].append({"name": "tunnel_consistency", "ok": ok})
            if not ok:
                result["ok"] = False
        except Exception as exc:  # pragma: no cover
            result["checks"].append({"name": "tunnel_consistency", "ok": False, "error": str(exc)})
            result["ok"] = False
    if check_kg and client.has_tool("mempalace_kg_timeline"):
        try:
            payload = client.call_tool("mempalace_kg_timeline", {})
            ok = isinstance(payload, (dict, list))
            result["checks"].append({"name": "kg_consistency", "ok": ok})
            if not ok:
                result["ok"] = False
        except Exception as exc:  # pragma: no cover
            result["checks"].append({"name": "kg_consistency", "ok": False, "error": str(exc)})
            result["ok"] = False
    return result


def validate_batch_operations(batch: dict[str, Any], approve_merge: bool) -> None:
    operations = batch.get("operations", [])
    if not isinstance(operations, list) or not operations:
        raise SystemExit("Batch has no operations")
    if not approve_merge:
        raise SystemExit("Merge execution requires explicit approval: use --approve-merge")
    if len(operations) > 3:
        raise SystemExit("Batch exceeds max 3 merges")
    high_risk = 0
    for op in operations:
        mode = op.get("mode")
        if mode != "merge":
            raise SystemExit(f"Unsupported merge mode: {mode}")
        if op.get("risk") == "high":
            high_risk += 1
    if high_risk > 1:
        raise SystemExit("Batch exceeds max 1 high-risk merge")


def run_execute(
    client: MCPClient,
    phase: str,
    batch_id: str,
    approve_merge: bool,
    plan_path: Path,
    artifacts_dir: Path,
) -> int:
    if not plan_path.exists():
        raise SystemExit(f"Missing plan file: {plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    batch = find_batch(plan, phase, batch_id)
    validate_batch_operations(batch, approve_merge)
    timestamp = now_utc_stamp()
    batch_log = artifacts_dir / f"batch-{timestamp}-{batch_id}.jsonl"
    rollback_log = artifacts_dir / f"rollback-{timestamp}-{batch_id}.json"
    regression_log = artifacts_dir / f"regression-{timestamp}-{batch_id}.json"

    mutations: list[dict[str, Any]] = []
    source_wings: list[str] = []
    target_wings: list[str] = []
    for op in batch.get("operations", []):
        source = op["source_wing"]
        target = op["target_wing"]
        source_wings.append(source)
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
    check_tunnels = phase in {"phase4"}
    check_kg = phase in {"phase5"}
    regression = run_regression_checks(client, source_wings, target_wings, check_tunnels, check_kg)
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


def run_store_auto(client: MCPClient, args: argparse.Namespace, artifacts_dir: Path) -> int:
    paths = session_paths(artifacts_dir, args.session_id)
    pending = read_json(paths["pending"], default_pending_state())
    content = args.content_file.read_text(encoding="utf-8") if args.content_file else args.content
    if content is None:
        raise SystemExit("store-auto requires --content or --content-file")

    start_calls = client.tool_calls
    client.call_tool("mempalace_status", {})

    base_payload = {
        "wing": args.wing,
        "room": args.room,
        "checkpoint": args.checkpoint,
        "durability": args.durability,
        "reuse_impact": args.reuse_impact,
        "uniqueness": args.uniqueness,
    }

    if args.checkpoint == "session_start":
        append_jsonl(paths["ledger"], [ledger_row(args.session_id, args.checkpoint, REASON_LIFECYCLE_READ_ONLY, base_payload)])
        write_json(paths["pending"], pending)
        print("session_start is read-only; no storage performed")
        return 0

    if args.sensitive:
        append_jsonl(
            paths["ledger"],
            [ledger_row(args.session_id, args.checkpoint, REASON_SENSITIVE_REDACTED, base_payload)],
        )
        write_json(paths["pending"], pending)
        print("Sensitive content detected; auto-store skipped")
        return 0

    duplicate_payload = client.call_tool(
        "mempalace_check_duplicate",
        {"content": content, "threshold": DUPLICATE_THRESHOLD},
    )
    is_duplicate, duplicate_similarity = normalize_duplicate_similarity(duplicate_payload)
    score = worth_score(args.durability, args.reuse_impact, args.uniqueness)
    confidence = confidence_score(
        confidence=args.confidence,
        source_count=args.source_count,
        contradiction_check=args.contradiction_check,
        user_confirmed=args.user_confirmed,
        recency_days=args.recency_days,
        duplicate_similarity=duplicate_similarity,
    )

    if score < 3:
        if args.checkpoint == "task_milestone":
            apply_budget(
                pending,
                {
                    "diary_writes": 0,
                    "kg_pairs": 0,
                    "tunnel_actions": 0,
                    "mcp_calls": client.tool_calls - start_calls,
                },
            )
        append_jsonl(paths["ledger"], [ledger_row(args.session_id, args.checkpoint, REASON_NOVELTY_LOW, base_payload)])
        write_json(paths["pending"], pending)
        print("Skipped: novelty/worth score below threshold")
        return 0
    if is_duplicate:
        if args.checkpoint == "task_milestone":
            apply_budget(
                pending,
                {
                    "diary_writes": 0,
                    "kg_pairs": 0,
                    "tunnel_actions": 0,
                    "mcp_calls": client.tool_calls - start_calls,
                },
            )
        append_jsonl(paths["ledger"], [ledger_row(args.session_id, args.checkpoint, REASON_DUPLICATE_HIGH, base_payload)])
        write_json(paths["pending"], pending)
        print("Skipped: high duplicate similarity")
        return 0
    if confidence < 0.8 and not args.user_instruction:
        if args.checkpoint == "task_milestone":
            apply_budget(
                pending,
                {
                    "diary_writes": 0,
                    "kg_pairs": 0,
                    "tunnel_actions": 0,
                    "mcp_calls": client.tool_calls - start_calls,
                },
            )
        append_jsonl(paths["ledger"], [ledger_row(args.session_id, args.checkpoint, REASON_CONFIDENCE_LOW, base_payload)])
        write_json(paths["pending"], pending)
        print("Skipped: confidence below auto-store threshold")
        return 0

    future_write_calls = 1
    if args.kg_subject and args.kg_predicate and args.kg_object:
        future_write_calls += 1
    if args.tunnel_source_wing and args.tunnel_source_room and args.tunnel_target_wing and args.tunnel_target_room:
        future_write_calls += 1
    projected_delta = {
        "diary_writes": 1,
        "kg_pairs": 1 if args.kg_subject else 0,
        "tunnel_actions": 1 if args.tunnel_source_wing else 0,
        "mcp_calls": (client.tool_calls - start_calls) + future_write_calls,
    }
    if args.checkpoint == "task_milestone" and budget_exceeded(pending, projected_delta):
        deferred = {
            "wing": args.wing,
            "room": args.room,
            "content": redact_content(content),
            "kg_subject": args.kg_subject,
            "kg_predicate": args.kg_predicate,
            "kg_object": args.kg_object,
            "tunnel_source_wing": args.tunnel_source_wing,
            "tunnel_source_room": args.tunnel_source_room,
            "tunnel_target_wing": args.tunnel_target_wing,
            "tunnel_target_room": args.tunnel_target_room,
            "confidence": args.confidence,
            "source_count": args.source_count,
            "contradiction_check": args.contradiction_check,
            "recency_days": args.recency_days,
            "user_confirmed": args.user_confirmed,
            "user_instruction": args.user_instruction,
        }
        pending.setdefault("deferred", []).append(deferred)
        apply_budget(
            pending,
            {
                "diary_writes": 0,
                "kg_pairs": 0,
                "tunnel_actions": 0,
                "mcp_calls": client.tool_calls - start_calls,
            },
        )
        append_jsonl(paths["ledger"], [ledger_row(args.session_id, args.checkpoint, REASON_BUDGET_EXCEEDED, base_payload)])
        write_json(paths["pending"], pending)
        print("Deferred: milestone budget exceeded")
        return 0

    redacted = redact_content(content)
    client.call_tool("mempalace_add_drawer", {"wing": args.wing, "room": args.room, "content": redacted, "added_by": "librarian-auto"})
    if args.kg_subject and args.kg_predicate and args.kg_object:
        client.call_tool(
            "mempalace_kg_add",
            {"subject": args.kg_subject, "predicate": args.kg_predicate, "object": args.kg_object},
        )
    if args.tunnel_source_wing and args.tunnel_source_room and args.tunnel_target_wing and args.tunnel_target_room:
        client.call_tool(
            "mempalace_create_tunnel",
            {
                "source_wing": args.tunnel_source_wing,
                "source_room": args.tunnel_source_room,
                "target_wing": args.tunnel_target_wing,
                "target_room": args.tunnel_target_room,
                "label": args.tunnel_label or "auto-store",
            },
        )

    apply_budget(
        pending,
        {
            "diary_writes": projected_delta["diary_writes"],
            "kg_pairs": projected_delta["kg_pairs"],
            "tunnel_actions": projected_delta["tunnel_actions"],
            "mcp_calls": client.tool_calls - start_calls,
        },
    )
    append_jsonl(paths["ledger"], [ledger_row(args.session_id, args.checkpoint, REASON_STORED_OK, base_payload)])
    write_json(paths["pending"], pending)
    print("Stored: auto memory event committed")
    return 0


def run_flush_auto(client: MCPClient, args: argparse.Namespace, artifacts_dir: Path) -> int:
    paths = session_paths(artifacts_dir, args.session_id)
    pending = read_json(paths["pending"], default_pending_state())
    deferred = list(pending.get("deferred", []))

    client.call_tool("mempalace_status", {})
    compacted = 0
    consolidated_rows: list[str] = []
    kg_triples: set[tuple[str, str, str]] = set()
    tunnel_intents: set[tuple[str, str, str, str, str | None]] = set()
    for item in deferred:
        content = item.get("content", "")
        duplicate_payload = client.call_tool(
            "mempalace_check_duplicate",
            {"content": content, "threshold": DUPLICATE_THRESHOLD},
        )
        is_duplicate, _ = normalize_duplicate_similarity(duplicate_payload)
        if is_duplicate:
            continue
        confidence = confidence_score(
            confidence=float(item.get("confidence", 0.0)),
            source_count=int(item.get("source_count", 1)),
            contradiction_check=str(item.get("contradiction_check", "pass")),
            user_confirmed=bool(item.get("user_confirmed", False)),
            recency_days=int(item.get("recency_days", 0)),
            duplicate_similarity=None,
        )
        if confidence < 0.8 and not bool(item.get("user_instruction", False)):
            continue
        compacted += 1
        consolidated_rows.append(f"{item.get('wing','?')}:{item.get('room','?')}:{content[:120]}")
        if item.get("kg_subject") and item.get("kg_predicate") and item.get("kg_object"):
            kg_triples.add(
                (
                    str(item["kg_subject"]),
                    str(item["kg_predicate"]),
                    str(item["kg_object"]),
                )
            )
        if (
            item.get("tunnel_source_wing")
            and item.get("tunnel_source_room")
            and item.get("tunnel_target_wing")
            and item.get("tunnel_target_room")
        ):
            tunnel_intents.add(
                (
                    str(item["tunnel_source_wing"]),
                    str(item["tunnel_source_room"]),
                    str(item["tunnel_target_wing"]),
                    str(item["tunnel_target_room"]),
                    item.get("tunnel_label"),
                )
            )

    ledger_rows = []
    if paths["ledger"].exists():
        for line in paths["ledger"].read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("reason") == REASON_STORED_OK:
                payload = entry.get("payload", {})
                ledger_rows.append(f"{payload.get('wing','?')}:{payload.get('room','?')}")
    summary = " | ".join(ledger_rows[-20:]) if ledger_rows else "no-stored-events"
    deferred_summary = " || ".join(consolidated_rows[-20:]) if consolidated_rows else "no-deferred-events"
    kg_summary = ";".join(f"{s}>{p}>{o}" for s, p, o in sorted(kg_triples)) if kg_triples else "none"
    tunnel_summary = (
        ";".join(f"{sw}/{sr}->{tw}/{tr}" for sw, sr, tw, tr, _ in sorted(tunnel_intents))
        if tunnel_intents
        else "none"
    )
    client.call_tool(
        "mempalace_add_drawer",
        {
            "wing": args.summary_wing,
            "room": args.summary_room,
            "content": (
                f"SESSION:{args.session_id}|AUTO:{summary}|DEFERRED:{compacted}|"
                f"NOTES:{deferred_summary}|KG:{kg_summary}|TUNNELS:{tunnel_summary}"
            ),
            "added_by": "librarian-auto-summary",
        },
    )
    for subject, predicate, obj in sorted(kg_triples):
        client.call_tool(
            "mempalace_kg_add",
            {"subject": subject, "predicate": predicate, "object": obj},
        )
    for source_wing, source_room, target_wing, target_room, label in sorted(tunnel_intents):
        client.call_tool(
            "mempalace_create_tunnel",
            {
                "source_wing": source_wing,
                "source_room": source_room,
                "target_wing": target_wing,
                "target_room": target_room,
                "label": label or "auto-flush",
            },
        )

    pending["deferred"] = []
    pending["usage"] = {"diary_writes": 0, "kg_pairs": 0, "tunnel_actions": 0, "mcp_calls": 0}
    write_json(paths["pending"], pending)
    report = {
        "session_id": args.session_id,
        "generated_at": now_utc_stamp(),
        "flushed_deferred": compacted,
        "summary_wing": args.summary_wing,
        "summary_room": args.summary_room,
    }
    write_json(paths["flush"], report)
    print(f"Flushed deferred items: {compacted}")
    print(f"Flush report: {paths['flush']}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge Partitioning Optimization CLI")
    parser.add_argument("--artifacts-dir", default=str(ARTIFACTS_DIR))
    parser.add_argument("--auto-store-dir", default=str(AUTO_STORE_DIR))
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
    exec_parser.add_argument("--approve-merge", action="store_true")

    rollback_parser = sub.add_parser("rollback")
    rollback_parser.add_argument("batch_id")
    rollback_parser.add_argument("--batch-log")

    store_parser = sub.add_parser("store-auto")
    store_parser.add_argument("--session-id", required=True)
    store_parser.add_argument("--checkpoint", choices=["session_start", "task_milestone", "session_end"], required=True)
    store_parser.add_argument("--wing", required=True)
    store_parser.add_argument("--room", required=True)
    store_group = store_parser.add_mutually_exclusive_group(required=True)
    store_group.add_argument("--content")
    store_group.add_argument("--content-file", type=Path)
    store_parser.add_argument("--durability", type=int, choices=[0, 1, 2], required=True)
    store_parser.add_argument("--reuse-impact", type=int, choices=[0, 1, 2], required=True)
    store_parser.add_argument("--uniqueness", type=int, choices=[0, 1], required=True)
    store_parser.add_argument("--confidence", type=float, default=0.0)
    store_parser.add_argument("--source-count", type=int, default=1)
    store_parser.add_argument("--contradiction-check", choices=["pass", "fail"], default="pass")
    store_parser.add_argument("--recency-days", type=int, default=0)
    store_parser.add_argument("--sensitive", action="store_true")
    store_parser.add_argument("--user-confirmed", action="store_true")
    store_parser.add_argument("--user-instruction", action="store_true")
    store_parser.add_argument("--kg-subject")
    store_parser.add_argument("--kg-predicate")
    store_parser.add_argument("--kg-object")
    store_parser.add_argument("--tunnel-source-wing")
    store_parser.add_argument("--tunnel-source-room")
    store_parser.add_argument("--tunnel-target-wing")
    store_parser.add_argument("--tunnel-target-room")
    store_parser.add_argument("--tunnel-label")

    flush_parser = sub.add_parser("flush-auto")
    flush_parser.add_argument("--session-id", required=True)
    flush_parser.add_argument("--summary-wing", required=True)
    flush_parser.add_argument("--summary-room", default="diary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifacts_dir = ensure_artifacts_dir(Path(args.artifacts_dir))
    auto_store_dir = ensure_artifacts_dir(Path(args.auto_store_dir))

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
            return run_execute(
                client,
                args.phase,
                args.batch_id,
                args.approve_merge,
                Path(args.plan),
                artifacts_dir,
            )
        if args.command == "rollback":
            batch_log = Path(args.batch_log) if args.batch_log else None
            return run_rollback(client, args.batch_id, batch_log, artifacts_dir)
        if args.command == "store-auto":
            return run_store_auto(client, args, auto_store_dir)
        if args.command == "flush-auto":
            return run_flush_auto(client, args, auto_store_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
