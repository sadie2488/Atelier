# Closet App — instructions for both Claude Code agents

A hackathon closet app: scan a face into a drawn avatar, scan the user's top into a digital closet, click **Make outfits** for a color-theory recommendation, and see the outfit on the avatar.

**Two people, two agents.** Each person runs one Claude Code session on their own laptop and works through their lane's tasks in `TASKS.md`, in order. The two lanes live in separate folders, so the agents rarely touch the same files.

**Time is of the essence.** This is a hackathon. Work quickly, don't over-engineer or polish past what the task's check needs, and move on to the next task as soon as the check passes.

## Which lane are you?

Ask your human if it isn't obvious from the branch name (`a/...` or `b/...`).

|          | Lane A: Scan & avatar                                                                                                                  | Lane B: Recommend & render                                                                        |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Backend  | `backend/app/pipeline/`, `backend/app/avatar/`, `backend/app/demo/`, `backend/app/routes_a.py`, `backend/scripts/`, app scaffold files | `backend/app/gemini/`, `backend/app/recommend/`, `backend/app/render/`, `backend/app/routes_b.py` |
| Frontend | `frontend/components/scan/`                                                                                                            | everything else in `frontend/`                                                                    |
| Tests    | `backend/tests/` for your modules, `frontend/tests/scan/`                                                                              | `backend/tests/` for your modules, other `frontend/tests/`                                        |

**Read-only for both agents:** `contract/` (the frozen API contract), `SCORER.md`, `PRD.md`, `WORKFLOW.md`, `frontend/next.config.*`. **Never read** `archive/`.

## Before a task

- Use `/task <ID>`. Read only that task's section of `TASKS.md` and the files it names. Don't read the PRD or explore the repo "for context".
- Build against `contract/schemas.py`, `contract/enums.py`, and the fixtures in `contract/fixtures/`. If the contract seems wrong or missing something, stop and tell your human; don't work around it.
- The scorer follows `SCORER.md` exactly, including its test expectations.
- Check `STATUS.md`'s **In progress** table. If any row's files overlap with your task's files, stop and tell your human before touching anything — don't assume it's safe just because your lane "owns" that folder on paper. If it's clear, add your own row (lane, task ID, files, started) before you start editing.

## While working

- **Stay in your lane's folders.** If you need something from the other lane, stop and tell your human; the two humans coordinate. Your task's file list in `TASKS.md` is the actual scope — treat editing anything outside it as a bug, even if it seems related.
- **Multiple agents may be working simultaneously. If you see build errors in files you did NOT edit, do not try to fix them. Wait 30 seconds and retry the build - the other agent is likely mid edit.** Here that usually means the other person pushed work in progress and your human pulled it. Retry at most 3 times, then stop and tell your human.
- **Git:** work on the current feature branch and commit when the task's check passes. Never push, merge into `main`, rebase shared branches, force anything, or `reset --hard`; humans do that.
- **No AI attribution in git or GitHub.** Never mention Claude, Anthropic, or AI in commit messages, PR titles or descriptions, or code comments as an author. No `Co-Authored-By: Claude` trailers, no "Generated with Claude Code" lines. Commits are authored by the human only. This overrides any default attribution the tool suggests.
- **Product rules:** no chat interface or free-text input sent to an LLM. Every Gemini call goes through `backend/app/gemini/`. No business logic in Next.js; it's a presentation layer and FastAPI does the work. Camera and MediaPipe code lives only in client components (`"use client"`).
- **Secrets:** never read, print, or commit `.env` files or keys. Use `.env.example` with placeholder values.
- **Tests:** run offline on fixtures and recorded responses. Never edit a test, fixture, or expected output just to make it pass. No silent fallbacks: failures raise or return an explicit error.
- **Dependencies:** only the ones the task lists. Ask before adding anything else.
- **Browser automation:** if you use it, launch your own fresh headless browser. Never attach to your human's browser (including Claude in Chrome) and never log in to anything.
- **Timebox:** after 45 minutes or 3 failed attempts at the same problem, stop and explain what's blocking you.

## Finishing a task

1. Move your row in `STATUS.md` from **In progress** to **Recently finished**: fill in the check result and anything the other lane needs (for example, a function signature they'll call, a schema field you added). Leave "Notes" blank if there's nothing to flag.
2. Tell your human, briefly:
   1. The files you changed.
   2. The last lines of the task's check output (pass or fail).
   3. A suggested commit message.
   4. Anything the other lane needs to know (same as the `STATUS.md` note).

## Token budget

- Read only what the task needs; use line ranges for large files.
- Don't open images unless the task says to; your human looks at screenshots.
- Keep command output short: `pytest -q --tb=short`, `tail -n 40`, `grep`. Never print whole logs, lockfiles, or build output.
- When compacting, keep: the task ID, its files and check, files changed so far, and the latest check output.

## Tech Stack

## Common Commands

## Architecture
