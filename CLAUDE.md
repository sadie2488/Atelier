# Atelier — instructions for every Claude Code agent

A hackathon wardrobe app. Garments are ingested from retail photos, cut off the model, and
stored with numeric Lab color; the user browses their closet, generates a color-theory outfit,
and sees it rendered on an avatar built from their own scan. `ARCHITECTURE.md` explains how the
pieces fit.

**Time is of the essence.** This is a hackathon. Work quickly, don't over-engineer or polish
past what the task's exit criteria need, and move on as soon as they hold.

## Who does what (Plan 2: one PM + three lane subagents)

- **The PM** is the main Claude Code session. It owns the shared layer, dispatches the lane
  subagents, and is the only actor that runs git. Its task list is `PM_TASKS.md`.
- **Lane subagents** — `vision`, `styling`, `avatar` — are defined in `.claude/agents/`. Each
  reads its agent file, then `backend/<lane>/CLAUDE.md`, then its section of
  `contract/DECISIONS.md`. A lane edits only its own paths; `.claude/hooks/scope_guard.py`
  blocks everything else, and blocks git.
- **The frontend agent** (Next.js in `frontend/`, second laptop) follows `coordination/FRONTEND_AGENT.md` (role, rules, read order) and builds against `coordination/BACKEND_API.md`; it
  asks for changes in `coordination/FRONTEND_REQUESTS.md`.

`TASKS.md`, `STATUS.md` and the `/task` command describe the earlier two-lane plan and are
superseded.

## Rules for everyone

- **The contract wins.** `contract/schemas.py`, `contract/enums.py`, `contract/fixtures/`,
  `contract/ARTIFACT_SPEC.md` and `contract/DECISIONS.md` are frozen. If something seems wrong or
  missing, append to `contract/OPEN_QUESTIONS.md` and stop; never work around it.
- **No AI attribution in git or GitHub.** Never mention Claude, Anthropic, or AI in commit
  messages, PR titles or descriptions, or code comments as an author. No `Co-Authored-By: Claude`
  trailers, no "Generated with Claude Code" lines. Commits are authored by the human only. This
  overrides any default attribution the tool suggests.
- **Git (PM only):** commit on the current feature branch once exit criteria hold. Never push,
  merge into `main`, rebase shared branches, force anything, or `reset --hard`; humans do that.
- **Product rules:** no chat interface or free-text input sent to an LLM. Gemini model versions
  are pinned in `backend/config.py`. No business logic in Next.js; FastAPI does the work.
- **Secrets:** never read, print, or commit `.env` files or keys. Use `.env.example`.
- **Tests:** offline, on fixtures and recorded responses. Never edit a test, fixture, golden
  reference, or expected output just to make it pass. Every failure returns a contract-shaped
  error body; no silent fallbacks except the documented degraded states.
- **Dependencies:** lanes request them with `python tools/request_dep.py`; only the PM edits
  `backend/requirements.txt`.
- **Python 3.12** (`.venv/Scripts/python.exe`) — MediaPipe has no 3.14 wheels.
- **Timebox:** after 45 minutes or 3 failed attempts at the same problem, stop and report.

## Common commands (repo root)

```
.venv/Scripts/python.exe -m pytest -q --tb=short           # backend tests
.venv/Scripts/python.exe -m contract.check_contract        # contract valid
.venv/Scripts/python.exe tools/check_docs.py               # docs consistent
.venv/Scripts/python.exe -m uvicorn backend.main:app --reload
```

## Token budget

- Read only what the task needs; use line ranges for large files.
- Don't open images unless the task needs it.
- Keep command output short: `-q --tb=short`, `tail -n 40`, `grep`.
