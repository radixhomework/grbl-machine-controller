# AGENTS.md — working rules for coding agents

Rules for AI agents (and anyone acting as one) working in this repository.
Project-specific details live in the repo's own documentation
(ARCHITECTURE.md and `docs/`) — read them before touching code.

## Commit policy

- **Never commit or push unless the user explicitly asked for it.**
  Finishing a task or passing tests is never consent to commit.
- If the user asks to hold for local testing, report "done, ready to test"
  and stop — don't ask again; wait for an explicit go.
- Conventional-commit style, English (`feat:`, `fix:`, `refactor:`,
  `docs:` …), body bullets explaining the why. Feature work on `feat/*`
  branches (this repo merges them to `main` on the user's request; a squash
  by the user on `main` is also an accepted pattern).
- When the working tree contains files the agent did not create, inspect
  them and say so before staging everything.
- Tags (`v*`) trigger release builds and GitHub releases — **never create
  or push tags unless explicitly asked.**

## Agent-local files are never committed

- **Never stage or commit agent-specific directories and files**
  (`.zcode/`, `.claude/`, `.agents/`, `.cursor/`, `.aider*`, and the like).
  They are machine-local configuration, not project content. The repo
  `.gitignore` covers them; if it doesn't yet, propose adding it rather
  than committing these paths.

## Quality gates

Before calling implementation work done, check what this repository has
configured:

1. **Unit tests** — `pytest` must pass (the suite covers the streamer,
   GRBL protocol, probe math, state, and job lifecycle; it runs on the
   simulator, no hardware needed).
2. **GitHub Actions `build` workflow** — tests plus per-target builds
   (Linux x64/ARM64, Windows x64) must be green; the packaged executables
   are the release artifacts.

SonarCloud / CodeQL are not configured for this repository; if they are
added later, their gates apply to changed code the same way. PR comments
(bot and human) must be addressed before merge.

## Iteration policy

Fix what was found, push, wait for fresh analyses, then re-check the gates
above — repeat until clean.

**Stop rule: 3 iterations maximum, autonomously.** After 3 fix/verify
iterations, stop and report remaining findings and what was tried; wait for
the user's decision.

## Testing stance

- The project ships a real unit suite — keep it green and extend it for
  core changes (protocol parsing, flow control, probe math) rather than
  testing by hand.
- The GRBL simulator (`app/core/fake_grbl.py`, `python -m app.main --fake`)
  is the way to exercise the full app without hardware; new protocol
  behavior goes there first, then under test.
- When the user says to do fewer tests and move on, move on — don't stall
  on ceremony.

## Architecture rule: the core never imports Qt

`app/core/` and `app/ha/` must stay Qt-free. Everything the UI shows comes
from `MachineState` subscriptions; every command goes through
`GRBLAdapter` or `JobManager`. UI state crosses threads only via the
`StateBridge` signal — never touch widgets from core threads. New GRBL
protocol behavior is added to the simulator first, then covered by a test.

## Workflow

- This repository does **not** use OpenSpec; plain branches + conventional
  commits are the workflow. (If OpenSpec is ever deployed here, reinstate
  the template's OpenSpec section.)
- Versioning: the single source of truth is `app/__version__`
  (`pyproject.toml` reads it). Bump it as part of the change that warrants
  a release; the user decides when to tag `v*`.

## Product & architecture documentation

**`ARCHITECTURE.md` is maintained and must stay up to date as part of the
development process — not as an afterthought.** Detailed, user-facing
documentation lives in `docs/` (usage, probing, configuration, mqtt,
development); keep the relevant page in the same change when behavior
changes.

- This repository deliberately has **no `PRODUCT.md`** — the project scope
  and goals live at the top of `ARCHITECTURE.md`. Don't create one unless
  the user asks.
- When starting a task, read `ARCHITECTURE.md` and the relevant `docs/`
  page first; if the code and the docs disagree, surface the discrepancy
  to the user instead of silently trusting either one.

## Documentation edits need approval

`AGENTS.md`, `ARCHITECTURE.md`, and `docs/` are never edited silently
beyond routine upkeep: substantive changes (new decisions, scope changes,
removed sections) are proposed to the user and applied after approval.
Routine sync of facts that the approved change already implies (e.g.
documenting the feature being merged) goes in directly.
