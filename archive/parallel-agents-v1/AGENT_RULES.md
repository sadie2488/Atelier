# AGENT_RULES.md

Read this entire file, and `CLAUDE.md`, before doing anything. These rules are non-negotiable.
A diff that breaks any rule is rejected whole, not patched.

## Repo layout and ownership

```
/contract/                  HUMAN (lane A). Schemas, enums, template_body.json, fixtures, FROZEN
/golden/                    HUMAN (lane A). Seed photos, scans, labels.csv
/db/                        HUMAN (lane B). Postgres log schema
/backend/
  app/main.py, routes_a.py  HUMAN (lane A)          app/routes_b.py  HUMAN (lane B)
  app/pipeline/, avatar/, scripts/   cv-pipeline-engineer   (lane A)
  app/demo/, scaffold files          backend-engineer       (lane A)
  app/gemini/               gemini-integrator      (lane B; the ONLY place Gemini is called)
  app/recommend/            recommender-engineer   (lane B)
  app/render/               render-engineer        (lane B)
  tests/<module>/           the module's expert
/frontend/
  next.config.*             HUMAN (lane B)
  components/scan/, tests/scan/      scan-ui-engineer      (lane A)
  app/, lib/, components/closet|outfit|shared/, config files   frontend-engineer (lane B)
/docs/, README.md           docs-writer            (lane B)
/.claude/                   HUMAN (lane B) config. Experts write only .claude/tasks/<ID>/REPLY.md
                            and .claude/tasks/<ID>/evidence/; test-runner and code-reviewer only
                            their own folder in .claude/reports/.
../closet-wt/<task-id>/     one isolated git worktree per task
../closet-venv/             one shared Python venv (human-installed)
```

The machine-checked version of this table is `.claude/scopes.json`.

## Scopes

1. Each expert has one exclusive scope and one lane in `.claude/scopes.json`. Scopes never overlap; `python3 .claude/scripts/check_scopes.py` warns if they do.
2. A task's allowlist is always inside its expert's scope. Experts edit only that allowlist, plus their own REPLY.md and evidence/.
3. The guard hook blocks edits outside your worktree, scope, or allowlist before they happen. If you're blocked, don't work around it: stop and report under **Needs**.
4. Edit files only with the Edit/Write tools. Never write files with shell commands (`sed -i`, `>`, `tee`, scripts that write files), because they bypass the guard; the final scope diff will still reject them.
5. Two tasks run in parallel only if `check_scopes.py --tasks <A> <B>` reports no overlap.

## Architect protocol

6. All coordination flows through the architect (each laptop's main session). Experts never talk to, invoke, or write to another expert, and never read or write another task's folder.
7. An expert's only instructions are its `.claude/tasks/<ID>/ANNOUNCEMENT.md` and the dispatch prompt. Experts never edit the announcement.
8. An expert's only answer is `.claude/tasks/<ID>/REPLY.md` from the template. Returning to the architect is the done signal.
9. Anything an expert needs from another expert goes under **Needs** in its REPLY. The architect relays it as a new announcement; if it's for the other lane, the humans pass a handoff between laptops.
10. The architect announces only with `announce.py`, only to its own lane's experts, and only after the human approves the plan. It never creates or widens scopes, edits the contract, implements code itself, or works around a refusal.

## Worktrees and git

11. Every task runs in its own worktree `../closet-wt/<ID>` on branch `agent/<lane>-<ID>`, created from `main` by `announce.py`. Experts are dispatched with `cwd` set to that worktree, and every shell command starts with `cd <worktree> &&`.
12. No agent runs git write commands. Permission deny rules and the guard block them. `announce.py` commits the announcement and, on `--collect`, the expert's work after a scope check.
13. Humans merge each reviewed branch as soon as the architect reports it (`git merge --no-ff`), push `main` immediately, and remove the worktree. The other laptop pulls before announcing. Rungs are checkpoints for testing the full flow, not merge windows.

## Parallel work

14. **Multiple agents may be working simultaneously. If you see build errors in files you did NOT edit, do not try to fix them. Wait 30 seconds and retry the build - the other agent is likely mid edit.**
15. Retry at most 3 times. If the errors persist, stop and report them with the full output.
16. Never install or upgrade shared tooling (the shared venv, global npm packages, Playwright browsers). `npm ci` from the existing lockfile inside your own worktree is allowed (`ui_check.sh` does it).
17. Use only the port in your announcement for any server you start, and stop it when done.

## Browser automation

18. Never share a browser automation session. Use `.claude/scripts/ui_check.sh`, which launches its own fresh headless browser, or launch your own isolated one; close it when done.
19. Never attach to the human's browser (including Claude in Chrome), another agent's browser, or another agent's tabs. Never log in to anything.

## Logging

20. Every action is logged with timestamps, session id, and agent id by an async hook (`.claude/hooks/log_action.py`): to `.claude/logs/actions.jsonl` in stage 1, to Postgres (`agent_actions`) in stage 2. Never edit, disable, or bypass the hooks or `.claude/settings.json`.
21. Never put secrets in commands, file contents, prompts, or REPLYs. The logger redacts common key formats, but don't rely on it.

## Token budget

22. Read only your allowlist files and the files your announcement names; use line ranges for large files. Never explore the repo for context.
23. Don't open images unless your task says to. Keep command output small (`-q --tb=short`, `tail`). Keep your REPLY under 40 lines.

## Forbidden actions

24. Never deploy, change hosting or database settings, or touch any cloud console.
25. Never read, write, print, or commit real secrets. Use `.env.example` placeholders only. Tests must run offline on fixtures and recorded responses.
26. Never add a dependency that is not in your announcement's approved list. Approved dependencies are pinned.
27. Never edit tests, the golden set, labels, or expected outputs to make a check pass.
28. Never stub, mock, or bypass the thing under test. Never add silent fallbacks: every failure raises or returns an explicit error status. (Fallbacks named in your announcement are required behavior and must be logged.)
29. Never add a chat interface or any free-text input that is sent to an LLM.
30. Never put business logic in Next.js API routes or server code. All logic lives in FastAPI.
31. Every Gemini call goes through `backend/app/gemini/`. No direct SDK imports anywhere else.
32. Camera and MediaPipe code lives only in client components (`"use client"`).
33. Maximum diff of ~600 changed lines, excluding tests and fixtures. If you need more, stop and ask for the task to be split.

## Definition of done

34. Run the **check** in your announcement exactly as written, and paste the actual output into your REPLY. Frontend checks run locally through `ui_check.sh`; there are no Vercel previews for agents.
35. Run `python3 .claude/scripts/check_scopes.py --diff <ID>` in your worktree; it must print `OK`. Paste it into your REPLY.
36. Your REPLY (`.claude/tasks/<ID>/REPLY.md`, from `.claude/tasks/_templates/REPLY.md`) always has: status; files changed; verification (command and pasted output); scope-check output; known issues; what you did not do; decisions; needs.

## Stopping

37. Timebox: 45 minutes or 3 failed attempts at the same problem, whichever comes first. Then stop and write a REPLY with status `blocked`.
38. If the announcement is ambiguous, stop and write a REPLY with status `blocked` and your question under **Needs**. Never guess at the contract.

## Human-side rules (for the team, not agents)

39. One architect session per laptop, with `.claude/lane.local` set to that laptop's lane. At most 2 experts running at once per laptop, and only with no scope-check warnings.
40. Approve every plan before announcements. Re-run nothing the architect already verified unless the review says so.
41. Merge each reviewed branch promptly: `git diff main...agent/<lane>-<id>`, `git merge --no-ff`, `git push`, `git worktree remove ../closet-wt/<id>`, `git branch -d agent/<lane>-<id>`. Pull (`git pull --ff-only`) before asking your architect to announce anything.
42. Human-owned files have one owner each (`human_owners` in `.claude/scopes.json`); change them only on the owner's laptop, push immediately, and tell the other human.
43. If a branch fights integration for more than 30 minutes, drop it and keep the last good `main`.
44. Overnight, only QUEUE tasks from `TASKS.md` are announced. Never debugging, integration, or anything touching deploys.
45. Stage 2 logging: before every rung, check `scope_violations` and `external_actions` in Postgres (stage 1: read `.claude/logs/actions.jsonl`).
