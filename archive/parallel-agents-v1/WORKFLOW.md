# WORKFLOW.md — two laptops, one repo (humans)

## The shape

```
            GitHub repo (origin) — main only; agent branches are never pushed
               ▲ push after every merge            ▲ push after every merge
               │ pull before every announce        │ pull before every announce
  Laptop A ────┘                                   └──── Laptop B
  lane a: cv-pipeline, scan-ui, backend-engineer         lane b: gemini, recommender, render, frontend, docs
  architect A + ≤2 experts                                architect B + ≤2 experts
  ../closet-wt/<ID>  worktrees                            ../closet-wt/<ID>  worktrees
```

- **Each laptop is one lane.** `.claude/lane.local` says which. Experts belong to exactly one lane, and their scopes never overlap, so the two laptops never edit the same file. Merge conflicts between laptops can only happen in human-owned files, and each of those has one owner (`human_owners` in `.claude/scopes.json`).
- **`main` on GitHub is the only thing the laptops share.** Agent branches stay local. Humans merge a reviewed branch into local `main`, push right away, and the other laptop pulls.
- **Cross-lane dependencies travel through `main`.** When laptop A merges task A1, its `.claude/tasks/A1/REPLY.md` lands in `main`. After laptop B pulls, `announce.py` on B sees A1 as done and allows B's tasks that depend on it. Until then it refuses, which is correct.
- **Vercel and DigitalOcean deploy from `main` on GitHub**, so a push is also a deploy. Push only merged, reviewed work.

## The routine (each human, all night)

1. `git pull --ff-only` (announce.py refuses if you're behind anyway).
2. Tell your architect what to build (`/build ...`), or which TASKS.md IDs to dispatch. Approve its plan.
3. Wait for its report. For each reviewed task, run the commands it gives you: `git diff`, `git merge --no-ff`, `git push`, `git worktree remove`, `git branch -d`.
4. Tell the other human "pushed <IDs>" (a chat message is enough). They pull.
5. Cross-lane needs: your architect writes a handoff file under `.claude/reports/handoff/`. Push it and tell the other human; their architect turns it into an announcement.

Contract changes after the freeze: lane A human only, both humans agree, push immediately, both architects are told.

## Saving tokens (humans)

Usage limits are shared by everything running on your account, so two architects plus their experts drain them fast. These habits matter most, roughly in order:

1. **`/clear` the architect after each merged batch.** Its state lives in the registry and task files, so nothing is lost. A session that's been open all night re-sends its whole history with every request.
2. **Sonnet by default.** Opus only for a hard planning step (`/model`), then switch back. docs-writer and test-runner already run on Haiku.
3. **At most 2 experts at once per laptop**, and stop idle sessions. Each one uses its own context.
4. **Disable MCP connectors you don't need while coding** (`/mcp`): Gmail, Drive, Slack, Canva, Figma. Check what's loaded with `/context`.
5. **Resume after long breaks with `/clear`**, not by continuing: after a long idle gap the cache has expired and the next message re-processes the whole conversation.
6. **Look at screenshots yourself** instead of asking Claude to.
7. **Watch `/usage`** at each rung so a limit doesn't surprise you at 3 AM.

## Stage 1 setup (tonight, about 30–45 minutes, before any real task)

Both laptops unless noted.

1. **Repo:** one GitHub repo; both humans clone it. Unzip the setup into the repo root; the lane B human commits and pushes it; the lane A human pulls.
2. **Lane:** `echo a > .claude/lane.local` on laptop A, `echo b > .claude/lane.local` on laptop B (gitignored).
3. **Python:** `python3 -m venv ../closet-venv` (next to the repo), then install the approved backend dependencies into it as tasks need them. `announce.py` points checks at it.
4. **Frontend (laptop B first, after S2 lands):** `npx playwright install chromium` once per laptop.
5. **Claude Code:** open it in the repo, run `/hooks` and `/permissions` once to confirm the guard, the logger, and the git deny rules are loaded. Approve the project hooks if asked.
6. **Logging:** nothing to do in stage 1. Actions queue to `.claude/logs/actions.jsonl`.
7. **Run the dry run below.** If it doesn't pass within about 90 minutes of starting setup, fall back to lite mode (end of this file).

## Stage 2 (after the first real feature merges)

1. Lane B human creates the Postgres database, runs `db/agent_log_schema.sql`, and shares the URL privately.
2. Both: `export AGENT_LOG_DATABASE_URL=...` in the shell that launches Claude Code (never in the repo), `pip install "psycopg[binary]"` for that `python3`, then `python3 .claude/hooks/log_action.py --replay` to upload the queue.

## Dry run (target: about 20 minutes, both laptops)

Two throwaway tasks that exercise every moving part with no dependencies and no product code: announce, refusal, dispatch with a pinned worktree, the guard, the expert's REPLY, collect, re-check, human merge, push, pull, and a cross-laptop dependency.

| Step | Laptop A | Laptop B |
| --- | --- | --- |
| 1 | `/dryrun` — announces **TA00** (cv-pipeline-engineer writes `backend/app/pipeline/dryrun.py` with `ping()` → `"pong"`) and dispatches it | `/dryrun` — tries **TB00** (recommender-engineer: `echo()` → `ping() + "!"`, depends on TA00). **Expected: REFUSED**, "dependency TA00 is not merged into main" |
| 2 | Expert finishes; architect runs `/collect TA00`, re-runs the check (`TA00 OK`), reports | Wait |
| 3 | Human: `git diff`, `git merge --no-ff`, `git push`, `git worktree remove`, `git branch -d` | — |
| 4 | Say "pushed TA00" | Human: `git pull --ff-only`, then `/dryrun` again. **Expected: announced and dispatched** |
| 5 | Guard probes (below) | Expert finishes; `/collect TB00`, check prints `TB00 OK`; human merges and pushes |
| 6 | Pull; `announce.py --status` shows TA00 and TB00 merged | Guard probes (below) |

**Guard probes** (ask your architect to try each and report what happened; each must be blocked):

1. "Run `git commit --allow-empty -m probe`" → blocked by the permission rules or the guard.
2. "Use the Write tool to create `../closet-wt/<any open task>/probe.txt`" → blocked: the architect never edits inside a worktree. (Run this while TA00 or TB00 is still open.)
3. "Announce a copy of your dry-run task with the other lane's expert" (e.g. TA99 → recommender-engineer) → REFUSED by announce.py.

**Pass criteria:** both checks print OK, both REPLYs are in `main` on both laptops, the step-1 refusal and all three probes behaved as expected, and `.claude/logs/actions.jsonl` has rows with `agent_type` set to the expert's name. Anything else: note it, and fix it or switch to lite mode before real tasks.

After the dry run, delete `backend/app/pipeline/dryrun.py` and `backend/app/recommend/dryrun.py` in a normal human commit.

## Lite mode (bailout)

If the full loop isn't working by the cutoff: keep scopes, worktrees, the guard, `CLAUDE.md`, and the no-git rule; skip `announce.py`. The architect dispatches experts directly with the task text from `TASKS.md` and the worktree path; humans create worktrees with `git worktree add ../closet-wt/<ID> -b agent/<lane>-<ID>` and commit the expert's work themselves after `check_scopes.py --diff <ID>` prints OK.
