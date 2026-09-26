---
task_id: TA01
title: short name of the task
agent: cv-pipeline-engineer
lane: a
depends_on: none
allowlist:
  - backend/app/pipeline/example.py
  - backend/tests/pipeline/test_example.py
approved_dependencies: none
check: cd {WT}/backend && {PY} -m pytest tests/pipeline/test_example.py -q
port: {PORT}
worktree: {WT}
---

# ANNOUNCEMENT: {ID} <title>

From: architect (lane <a|b>)
To: <expert>

## Goal

[What to build, in 2–5 sentences. One task, one expert, one scope.]

## Context from the architect

- [ARCHITECT: the exact contract models/enums/fixtures this task uses]
- [ARCHITECT: prior decisions (from REPLYs or the registry) and interfaces it can call, verbatim]

## Not in scope

- [what not to do, including anything that belongs to another expert]

## Working rules for this task

- Your worktree is `{WT}`. Every shell command starts with `cd {WT} &&`.
- Edit files only with the Edit/Write tools, only inside your allowlist, plus `.claude/tasks/{ID}/REPLY.md` and `.claude/tasks/{ID}/evidence/`.
- Never run git write commands (add, commit, push, merge, checkout...). The architect commits your work.
- If a build fails in files you did not edit: wait 30 seconds and retry, at most 3 times, then report.
- Read only your allowlist files and the files named under "Context from the architect". Don't explore the repo, and don't open images unless the goal says to.
- Keep output small (`-q --tb=short`, `tail -n 40`); paste only the final result lines into your REPLY. Keep the REPLY under 40 lines.

## When you're done

1. Run the check: `{CHECK}`
2. Run `cd {WT} && python3 .claude/scripts/check_scopes.py --diff {ID}` (must print OK).
3. Write `.claude/tasks/{ID}/REPLY.md` from `.claude/tasks/_templates/REPLY.md`, pasting both outputs.
4. Return to the architect with one line: `{ID} <done|blocked|failed>: see REPLY.md`.

Never contact another expert. If you need something from one, put it under **Needs** in your REPLY.
