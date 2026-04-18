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
3. Install or repair MemPalace in dedicated `~/.mempalace/venv` if needed.
   Reuse existing healthy install first, including `~/.venv`, before creating new venv.
4. Configure Codex CLI, Claude Code, or Gemini CLI MCP and hooks.
5. Run narrow bootstrap:
   - `mempalace_status`
   - `architecture`
   - `decisions`
   - one targeted search
   - one traversal
6. Init/mine new or stale projects.
7. File end-session diary, KG updates, and tunnel checks with duplicate gating.

## Setup Helper

Dry run:

```bash
python3 scripts/setup_mempalace.py --dry-run --harness codex
python3 scripts/setup_mempalace.py --dry-run --harness claude
python3 scripts/setup_mempalace.py --dry-run --harness gemini
```

Real run:

```bash
python3 scripts/setup_mempalace.py --harness codex
python3 scripts/setup_mempalace.py --harness both
python3 scripts/setup_mempalace.py --harness gemini
```

Options:
- `--install-source auto|local|pypi`
- `--repo ~/codes/mempalace`
- `--venv ~/.mempalace/venv`
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
