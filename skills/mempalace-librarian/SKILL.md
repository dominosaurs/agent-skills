---
name: mempalace-librarian
description: >
  Librarian for MemPalace. Keep project and session memory organized,
  connected, retrievable, and token-cheap. Ensure MemPalace MCP works when
  needed, bootstrap context narrowly, mine new or stale projects, and file
  dense AAAK memory with durable graph links.
---

# MemPalace Librarian

You are librarian for long-term AI memory.

Job:
- enforce MCP-first memory operations (`mempalace_status` must succeed before memory flow)
- bootstrap minimal context with bounded MCP calls before broad local scanning
- run gated auto-store at lifecycle checkpoints (`session_start`, `task_milestone`, `session_end`)
- keep durable memory quality high with duplicate, confidence, privacy, and budget gates
- run memory optimization through explicit workflow (`analyze` -> `plan` -> approved `execute` -> `rollback`)
- apply merge-only wing consolidation with explicit approval and regression checks
- keep cross-project durability via constrained KG and tunnel updates

Goal: maximize memory signal per token.

## Core Rules

- MemPalace first, repo second.
- If task needs memory, make MemPalace MCP work before normal project work.
- Prefer MCP for reads/writes once available.
- Keep retrieval narrow. Smallest useful context first.
- This skill assumes MemPalace runtime is already installed and configured.
- If MemPalace MCP is unavailable, stop immediately.
- Do not mutate memory optimization state without explicit execute approval.
- Use only `merge` behavior for wing consolidation.

## Fast Path

1. Call `mempalace_status`.
2. If status call fails or is unavailable, stop immediately and report MCP unavailable.
3. Resolve project root.
4. Detect wing.
5. Init/mine if new, unmined, or stale.
6. Prove the mined wing is retrievable through MCP filters/search.
7. Continue coding work.

## Auto Activation For Context Fill

Use this skill automatically when task-critical context is insufficient.

Trigger condition:
- context is insufficient when the agent cannot resolve task-critical who/what/why from current thread plus open files within 2 targeted local reads

Skip condition:
- skip auto-activation when the task is self-contained in currently open files and does not require cross-session or cross-project memory

Decision tree:
1. evaluate trigger condition
2. if skip condition is true, continue task without librarian bootstrap
3. if triggered, run minimal bootstrap budget (up to 6 MCP calls):
   - `mempalace_status`
   - `mempalace_list_drawers` for target wing (single page)
   - one targeted `mempalace_search`
   - optional `mempalace_follow_tunnels` (1 hop)
   - optional second targeted `mempalace_search` if ambiguity remains
4. if `mempalace_status` fails, stop immediately (hard-stop)
5. if ambiguity remains after minimal budget, run one escalation step before repo-wide scanning:
   - one additional room-specific `mempalace_list_drawers`
   - one additional targeted `mempalace_search`
6. if still insufficient, allow constrained local repo scan
7. memory optimization commands are not auto-run from this flow; they remain explicit and non-default

## Requirements

- MemPalace must already be installed and configured in the active harness.
- MCP server for MemPalace must be available to this agent session.
- If MCP is unavailable, runtime repair is out of scope for this skill.

Official install and setup guide:
- https://mempalaceofficial.com/guide/getting-started

## Auto Memory Store And Micro Memory Optimization

### Lifecycle Policy

Auto store runs only at lifecycle checkpoints:

1. `session_start`: read-only bootstrap, no writes
2. `task_milestone`: conditional micro-store only when worth gate passes
3. `session_end`: mandatory consolidated store

Do not run continuous per-turn storage.

### Worth Memory Gate

At milestone, store only when memory is worth storing.

Score range: `0-5`. Store if score is `>= 3`.

Score components:

1. durability (`0-2`): likely to remain true/useful
2. reuse impact (`0-2`): likely to save future reasoning/time
3. uniqueness (`0-1`): not already stored (duplicate gate passes)

Milestone store candidates include:

1. durable decision changes
2. blocker root cause identified/fixed
3. durable cross-wing relation
4. durable user preference/constraint change

### Confidence Gate

Use confidence bands before auto-store:

1. `>= 0.8`: eligible for auto-store
2. `0.5-0.79`: suggestion only, no auto-write
3. `< 0.5`: do not store unless explicitly requested

Confidence must use observable signals:

1. independent source count
2. contradiction check result
3. explicit user confirmation presence
4. recency relevance
5. duplicate similarity distance

Override:
- explicit user instruction for durable preference/constraint is treated as high-confidence store.

### Duplicate Gate

Run `mempalace_check_duplicate` before each write, including session-end flush.

Default auto-store threshold: `0.92`.

If duplicate similarity exceeds threshold:

1. skip full write
2. write tiny delta only if net-new durable information exists

### Privacy And Redaction Gate

Exclude sensitive categories from auto-store by default:

1. secrets, tokens, credentials
2. unnecessary personal identifiers
3. highly sensitive personal/legal/medical data
4. raw debug dumps/log blobs

Redaction rules before storing:

1. mask key-like strings
2. remove exact paths unless required for retrieval
3. replace raw IDs/emails with stable aliases where possible
4. store decision summary, not raw payload

### Micro Memory Optimization Policy

Run micro memory optimization after each successful store event, limited to touched scope only.

Scope checks:

1. duplicate sanity for touched room
2. room assignment sanity
3. wing naming normalization check for touched wing
4. KG/tunnel consistency for touched entities only

Default mode is non-destructive:

1. detect and recommend
2. no merge/move/delete without explicit approved execute step

### Budget Controls

Per milestone budget:

1. max 1 diary write
2. max 1 KG add/invalidate pair
3. max 1 tunnel action
4. max 8 MCP calls total for store + micro-memory-optimization checks

When budget is exceeded:

1. defer remaining intents to queue
2. flush at `session_end`

### Queue, Ledger, And Artifacts

Artifacts path:
- `skills/mempalace-librarian/.artifacts/auto-store/`

Files:

1. `ledger-<session>.jsonl`
2. `pending-store-<session>.json`
3. `flush-report-<session-end>.json`

Record each decision with reason code:

1. `STORED_OK`
2. `NOVELTY_LOW`
3. `DUPLICATE_HIGH`
4. `CONFIDENCE_LOW`
5. `BUDGET_EXCEEDED`
6. `SENSITIVE_REDACTED`

### Session-End Compaction

At `session_end`:

1. flush pending queue with duplicate and confidence gates
2. compact micro notes into one consolidated AAAK diary drawer
3. derive KG/tunnel updates from consolidated durable facts only
4. keep micro notes as operational artifacts, not long-term drawers

## Memory Partitioning Optimization

### Scope

- This policy optimizes MemPalace memory partitioning phase-by-phase.
- Memory optimization is not default behavior.
- Memory optimization can run only when symptoms are detected.
- If `mempalace_status` fails, stop immediately; do not run optimize diagnostics or mutations.

### Terminology

- canonical wing naming standard: `kebab-case`
- normalization rules:
  - lowercase letters and digits only
  - words separated by single `-`
  - remove leading punctuation/underscores
  - normalize `_` to `-`
  - disallow `wing-` prefix unless literally part of project name
- examples:
  - `.gemini` -> `gemini`
  - `wing_gemini_cli` -> `gemini-cli`
  - `agent_skills` -> `agent-skills`

### Triggers

Run memory optimization diagnostics only when at least one trigger is true:

1. wing-name collision trigger: two or more wings normalize to the same canonical key
2. duplicate-hit trigger: for baseline scoped queries, 30% or more of top-10 hits are cross-wing near-duplicates
3. ambiguity trigger: 3 or more wings appear in top-10 for a project-scoped query
4. tunnel redundancy trigger: 2 or more tunnels represent the same source-target semantic intent
5. KG conflict trigger: any active conflicting triple with same `subject+predicate` and no invalidation chain

### Phases

1. phase 1: wing normalization and alias consolidation
2. phase 2: room normalization inside canonical wings
3. phase 3: drawer atomization and dedup quality pass
4. phase 4: tunnel pruning and durable-link completion
5. phase 5: KG integrity pass (invalidate stale, add missing durable facts)

Do not progress to the next phase until current phase regression checks pass.

### Command Contract

Strict command separation:

1. `analyze`: diagnostics only, no writes
2. `plan`: batch plan generation only, no writes
3. `execute <phase> <batch-id> --plan <plan.json> --approve-merge`: apply one approved merge batch (writes allowed)
4. `rollback <batch-id>`: revert one executed batch
5. `store-auto`: gated auto memory store event
6. `flush-auto`: session-end deferred consolidation and derived durable updates

Command entrypoint:
- `python skills/mempalace-librarian/scripts/partition_optimize.py <subcommand> ...`
- agent-agnostic MCP resolution:
  - `--harness auto|codex|claude|gemini`
  - explicit override: `--mcp-command <cmd> --mcp-arg <arg> ...`

If user says "optimize now" without phase or batch detail, default to `analyze` only.

### Approval Gates

- Approval unit is phase + batch.
- No mutations happen without explicit approval for the current batch.
- Batch size limits:
  - max 3 wing merges per batch, or
  - max 1 high-risk merge per batch
- only `merge` behavior is supported.
  - move source drawers to target
  - source wing must end empty after execution

### Regression Checks

Run after every executed batch:

1. `mempalace_status` succeeds
2. `mempalace_list_drawers(wing=...)` succeeds for affected canonical wings
3. representative `mempalace_search` queries show expected precision/ambiguity profile
4. if phase touches tunnels or KG, run tunnel/KG consistency checks

Fail closed: if any check fails, stop further batches.

### Rollback

- Create pre-batch snapshot manifest with drawer ids, source/target, and metadata hash.
- Record reversible mutation log for each change.
- On regression failure:
  1. rollback current batch automatically
  2. validate post-rollback with status/list/search
  3. mark batch as blocked for manual review
  4. do not continue to the next batch or phase

### Diagnostics Artifacts

- Store operational artifacts at:
  - `skills/mempalace-librarian/.artifacts/partition-optimization/`
- Files:
  - `diagnostic-<timestamp>.json`
  - `plan-<timestamp>.json`
  - `batch-<timestamp>.jsonl`
  - `rollback-<timestamp>.json`
  - `regression-<timestamp>.json`
- Do not auto-file these artifacts into MemPalace drawers or KG.

### Baseline Query Set

- Use a hybrid baseline for reproducible diagnostics:
  1. static core queries (stable comparison)
  2. dynamic add-on queries from current top wings/rooms
- Dynamic caps:
  - max 10 dynamic queries total
  - max 2 dynamic queries per top wing
  - target analysis budget: 30 or fewer search/list calls
  - stop early when trigger evidence is sufficient
- Report static and dynamic metrics separately.

### User Notice

When triggers are detected, emit concise `Memory Optimization Suggested` notice:

1. phase candidate
2. symptom summary and affected scope
3. estimated calls and token-cost range
4. risk level
5. expected quality gain
6. recommended next command (`analyze` or `plan`)

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

## Project Metadata Files

MemPalace may create `mempalace.yaml` and `entities.json` in a project root.
Treat them as retrieval-shaping metadata:
- `mempalace.yaml` stabilizes wing name, room routing, and project mining hints
- `entities.json` stabilizes durable people/projects/tools/domains for metadata and graph links

As librarian:
- inspect these files if present before mining
- create or improve them when auto-detection would produce weak rooms/entities
- keep only durable shared truth, not transient session notes
- prefer project-specific rooms/entities that improve future retrieval
- do not commit them blindly; they may be local generated files
- if they encode reusable project truth, say so and ask or intentionally stage them

For skill repos, curated metadata is useful when it names:
- the skill collection/project
- individual skills
- tools or protocols the skills manage
- supported harnesses or platforms
- durable cross-project relationships

## Initialized vs Mined

Track these separately:
- initialized: project root has usable `mempalace.yaml` and `entities.json`
- mined: MCP can retrieve the project wing through status/list/search

A project can be mined but not initialized, or initialized but not mined.
Do not infer one from the other.

Initialization check:
1. resolve project root
2. check for `mempalace.yaml`
3. check for `entities.json`
4. if either is missing or low quality, treat initialization as incomplete

Mining check:
1. identify expected wing
2. call `mempalace_status`
3. call `mempalace_list_drawers(wing=<wing>)`
4. call targeted `mempalace_search(..., wing=<wing>)`

If not initialized:
- inspect/curate `mempalace.yaml` and `entities.json`
- run project initialization flow through the available MemPalace interface
- then mine or re-mine if needed

If initialized but not mined:
- run project mining flow through the available MemPalace interface
- verify MCP status/list/search

## New / Unmined / Stale Project

New project:
- review/curate `mempalace.yaml` and `entities.json`
- run project initialization flow through the available MemPalace interface
- default project mining flow through the available MemPalace interface

Existing but unmined/stale:
- review/curate `mempalace.yaml` and `entities.json` when present or useful
- default project mining flow through the available MemPalace interface

Prefer one mine now over repeated repo rereads.

After mining, verify in MCP:
- `mempalace_status` includes expected wing and count
- `mempalace_list_drawers(wing=<wing>)` returns drawers
- targeted `mempalace_search(..., wing=<wing>)` returns relevant content

If only closet/queue-like results exist but wing drawers are absent, treat the mine as failed.

## Minimal Bootstrap

Default session-start budget:
1. `mempalace_status`
2. identify wing
3. identify available rooms from status, drawer list, or `mempalace.yaml`
4. `mempalace_list_drawers` for the most relevant project-specific rooms
5. one targeted `mempalace_search`
6. one traversal from a real room if tunnels exist

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

Before filing diary/KG/tunnels:
- confirm MCP still responds
- if storage was changed, verify status/list/search for the active wing
- skip or defer filing if MCP writes cannot be verified

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

Keep memory connected across projects.

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
5. verify new tunnel with `mempalace_follow_tunnels` or `mempalace_list_tunnels`

Do not tunnel generic tech words, one-off coincidence, or temporary debugging overlap.
