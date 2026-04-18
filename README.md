# Agent Skills

Collection repo for reusable agent skills.

## Layout

```text
agent-skills/
├── .gitignore
├── README.md
└── skills/
    └── mempalace-librarian/
        ├── README.md
        ├── SKILL.md
        ├── scripts/
        └── tests/
```

## Skills

- `mempalace-librarian` — MemPalace-first librarian skill for install, MCP setup, token-cheap bootstrap, mining, filing, and tunnel hygiene across Codex, Claude, and Gemini CLI.

## Validation

Main skill includes:
- unit tests under `skills/mempalace-librarian/tests`
- setup helper under `skills/mempalace-librarian/scripts`
- publish checklist in [`PUBLISH_CHECKLIST.md`](/home/dominos/codes/agent-skills/PUBLISH_CHECKLIST.md)
