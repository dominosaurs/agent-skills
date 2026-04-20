# MemPalace Librarian

Skill for AI coding agents that want MemPalace useful fast, not noisy.

Purpose:
- enforce MemPalace MCP accessibility before memory work
- bootstrap project context with low token cost
- mine new or stale projects automatically
- file durable AAAK memory, KG facts, and cross-project tunnels

## Structure

```text
mempalace-librarian/
├── README.md
├── SKILL.md
├── scripts/
│   └── partition_optimize.py
└── tests/
    └── test_partition_optimize.py
```

## What Skill Does

1. Detect current project root and likely wing.
2. Verify MCP availability with `mempalace_status`.
3. Stop immediately if MCP is unavailable.
4. Run narrow bootstrap:
   - `mempalace_status`
   - `architecture`
   - `decisions`
   - one targeted search
   - one traversal
5. Init/mine new or stale projects.
6. File end-session diary, KG updates, and tunnel checks with duplicate gating.

Auto-activation policy:
- auto-activates for context fill only when task-critical context is insufficient, with strict MCP-first budgeted bootstrap and hard-stop on MCP failure.

## Requirements

- MemPalace runtime must already be installed and configured for the harness.
- MemPalace MCP server must be reachable from the active agent session.
- If `mempalace_status` fails, stop and fix runtime/setup outside this skill.

Official install and setup steps:
- https://mempalaceofficial.com/guide/getting-started

## Scope Boundary

This skill does not:
- create or repair virtual environments
- install or upgrade MemPalace binaries
- rewrite harness MCP/hook runtime configuration

## Command Surface

`partition_optimize.py` provides explicit optimization workflow commands:
- `analyze`
- `plan`
- `execute <phase> <batch_id> --plan <plan.json> --approve-merge`
- `rollback <batch_id>`
- `store-auto --session-id ... --checkpoint ... --wing ... --room ...`
- `flush-auto --session-id ... --summary-wing ... [--summary-room ...]`

Merge policy:
- only `merge` mode is supported for wing consolidation

MCP resolution is agent-agnostic:
- `--harness auto|codex|claude|gemini`
- explicit override via `--mcp-command` and repeated `--mcp-arg`
