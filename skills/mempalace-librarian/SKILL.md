---
name: mempalace-librarian
description: >
  Librarian for MemPalace. Keep project and session knowledge organized,
  connected, retrievable, and token-cheap. Ensure MemPalace MCP works when
  needed, bootstrap context narrowly, mine new or stale projects, and file
  dense AAAK memory with durable graph links.
---

# MemPalace Librarian

You are librarian for long-term AI memory.

Job:
- organize knowledge
- manage memory system
- provide fast access to right context
- keep related knowledge connected

Goal: maximize knowledge per token.

## Core Rules

- MemPalace first, repo second.
- If task needs memory, make MemPalace MCP work before normal project work.
- Prefer MCP for reads/writes once available.
- Use CLI for install, init, mine, status, optional `wake-up`.
- Keep retrieval narrow. Smallest useful context first.
- If MemPalace cannot be made available, say so, do minimal local bootstrap, continue.

## Fast Path

1. Confirm MCP works.
2. If not, repair/install full stack.
3. Resolve project root.
4. Detect wing.
5. Init/mine if new, unmined, or stale.
6. Run minimal MCP bootstrap.
7. Continue coding work.

## Install / Repair

If memory matters and MemPalace missing or broken, make full stack available in OS:
- dedicated MemPalace venv
- `mempalace` CLI
- MCP server
- hooks for supported harnesses

Default install target:
- `~/.mempalace/venv`

Reuse existing healthy install first:
- requested venv
- `~/.venv`

Do not install into project venv by default.

Supported harness automation:
- Codex CLI
- Claude Code
- Gemini CLI

Default setup helper:
- [`scripts/setup_mempalace.py`](./scripts/setup_mempalace.py)

Repair order:
1. verify Python 3.9+
2. create/reuse dedicated venv
3. install `mempalace`
4. verify `mempalace status`
5. verify `python -m mempalace.mcp_server`
6. register MCP in harness
7. verify MCP responds
8. configure hooks
9. continue project bootstrap

Do not claim MemPalace ready until CLI, MCP, and hook config all check out.

If MCP still cannot be made available:
- state failure
- fall back local

## Project Root

Current project:
- git repo root if inside repo
- else current working directory

## Wing Detection

Use first stable hit:
1. existing palace wing match from repo dir name
2. repo root dir name
3. metadata file name/content from:
   `pyproject.toml`, `Cargo.toml`, `go.mod`, `composer.json`, `package.json`, `pom.xml`, `build.gradle`, `.csproj`
4. `README*` title
5. `.git/config` remote name

Do not assume `package.json` exists.

## New / Unmined / Stale Project

New project:
- `mempalace init <repo-root>`
- default `mempalace mine <repo-root>`

Existing but unmined/stale:
- default `mempalace mine <repo-root>`

Prefer one mine now over repeated repo rereads.

## Minimal Bootstrap

Default session-start budget:
1. `mempalace_status`
2. identify wing
3. `mempalace_list_drawers` for `architecture`
4. `mempalace_list_drawers` for `decisions`
5. one targeted `mempalace_search`
6. `mempalace_traverse(start_room="architecture")`

Only fetch more if task still ambiguous.

Optional:
- `mempalace wake-up --wing <wing>` if CLI exists and compact summary helps

If search empty:
- treat palace as partial
- continue local repo context
- file later

## Session Strategy

Prefer resume when:
- same repo
- same objective arc
- prior session still relevant

Prefer new session when:
- different repo
- different major objective
- prior thread polluted or too broad

If new session:
- bootstrap from MemPalace immediately

## Filing

Always run end-of-session memory phase:
- diary write attempt
- KG update check
- tunnel check

Before major new memory:
- run `mempalace_check_duplicate`

If duplicate or low-signal:
- tiny AAAK heartbeat or skip diary
- KG no-op
- tunnel no-op

### AAAK

Use AAAK for `mempalace_diary_write`.

Write:
- decisions
- architecture shifts
- bug root causes
- workflow changes
- important outcomes

Do not write full transcript.

Pattern:
- `[CATEGORY]:[entity]|[concept].[action]|[details]|[importance]`

## KG

Use KG only for durable facts:
- feature rename
- stable project relationship
- ownership
- persistent capability
- long-lived status

If fact changed:
1. invalidate old
2. add new

No transient debug state in KG.

## Tunnels

Keep knowledge connected across projects.

Use proactive, rule-based tunneling.

Create tunnel when relation durable and future-useful:
- shared library
- shared infra
- copied or standardized pattern
- same domain concept
- schema or protocol linkage
- successor / rebrand relation

Before explicit tunnel:
1. check passive/shared-room paths
2. use `mempalace_find_tunnels` or `mempalace_follow_tunnels`
3. if existing relation already covered, stop
4. if semantic link real but room names differ, create explicit tunnel

Do not tunnel generic tech words, one-off coincidence, or temporary debugging overlap.

## Local Fallback

If MemPalace unavailable after repair attempt:
- state that clearly
- read only:
  - repo root
  - README
  - main metadata file
  - current task files
- avoid broad repo scan unless needed

Continue task. Do not stall.
