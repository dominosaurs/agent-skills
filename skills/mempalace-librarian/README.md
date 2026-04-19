# MemPalace Librarian

Skill for AI coding agents that want MemPalace useful fast, not noisy.

Purpose:
- make MemPalace available in OS when memory matters
- make MCP work before normal MemPalace flow
- bootstrap project context with low token cost
- mine new or stale projects automatically
- file durable AAAK memory, KG facts, and cross-project tunnels

## Structure

```text
mempalace-librarian/
├── README.md
├── SKILL.md
├── scripts/
│   └── setup_mempalace.py
└── tests/
    └── test_setup_mempalace.py
```

## What Skill Does

1. Detect current project root and likely wing.
2. Ensure MemPalace CLI + MCP are usable.
3. Use dedicated runtime at `$XDG_DATA_HOME/mempalace-librarian/venv` or `~/.local/share/mempalace-librarian/venv`.
4. Create runtime only when missing; if existing runtime is broken, stop immediately without config writes.
5. Rewire Codex CLI, Claude Code, and Gemini CLI MCP to the dedicated runtime on every run.
6. Configure hooks (unless `--skip-hooks`) for all harnesses.
5. Run narrow bootstrap:
   - `mempalace_status`
   - `architecture`
   - `decisions`
   - one targeted search
   - one traversal
7. Init/mine new or stale projects.
8. File end-session diary, KG updates, and tunnel checks with duplicate gating.

## Setup Helper

Dry run:

```bash
python3 scripts/setup_mempalace.py --dry-run
```

Real run:

```bash
python3 scripts/setup_mempalace.py
```

Options:
- `--install-source auto|local|pypi` (default: `pypi`)
- `--repo ~/codes/mempalace`
- `--palace /custom/palace/path`
- `--skip-hooks`

## Publish Notes

Current quality bar:
- script syntax checked
- config merge behavior unit tested
- MCP handshake verifier checks `initialize` + `tools/list`
- temp-path smoke test covers Codex file writes

Still recommended before broad public release:
- run real install once on fresh machine or clean HOME
- run live Codex MCP verification
- run live Claude Code verification where `claude` CLI exists
