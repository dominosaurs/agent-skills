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
   - target wing drawer listing (single page)
   - most relevant project-specific rooms
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

`partition_optimize.py` provides explicit memory optimization workflow commands:
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

## Behavior Summary

Runtime and bootstrap:
- hard-stop when `mempalace_status` is unavailable
- bounded MCP-first context fill before local broad scans

Memory optimization:
- explicit workflow only: `analyze` -> `plan` -> approved `execute` -> `rollback`
- `execute` requires `--approve-merge`
- post-execute regression checks must pass before continuing

Auto store:
- checkpoint lifecycle: `session_start` (read-only), `task_milestone` (gated), `session_end` (consolidation)
- gates: duplicate, confidence, privacy/redaction, milestone budget

Flush behavior:
- `flush-auto` compacts deferred notes into one consolidated summary drawer
- derives deduped KG/tunnel updates from consolidated deferred durable facts

## Operator Quickstart

Analyze:

```bash
python skills/mempalace-librarian/scripts/partition_optimize.py analyze --harness auto
```

Plan from latest diagnostic:

```bash
python skills/mempalace-librarian/scripts/partition_optimize.py plan --harness auto
```

Execute approved merge batch:

```bash
python skills/mempalace-librarian/scripts/partition_optimize.py execute phase1 phase1-b1 --plan /path/to/plan.json --approve-merge --harness auto
```

Rollback batch:

```bash
python skills/mempalace-librarian/scripts/partition_optimize.py rollback phase1-b1 --harness auto
```

Store auto event:

```bash
python skills/mempalace-librarian/scripts/partition_optimize.py store-auto \
  --session-id s1 \
  --checkpoint task_milestone \
  --wing project-a \
  --room decisions \
  --content "Decision summary" \
  --durability 2 \
  --reuse-impact 2 \
  --uniqueness 1 \
  --confidence 0.9 \
  --source-count 2 \
  --contradiction-check pass
```

Flush deferred consolidation:

```bash
python skills/mempalace-librarian/scripts/partition_optimize.py flush-auto --session-id s1 --summary-wing project-a --summary-room diary --harness auto
```
