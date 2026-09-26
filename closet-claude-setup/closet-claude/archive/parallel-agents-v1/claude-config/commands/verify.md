---
description: Independently re-verify a task's done-check with the test-runner agent
argument-hint: <task-id>
---

# Verify

Dispatch `test-runner` for task **$1** using the done-check exactly as written in `.claude/tasks/$1/ANNOUNCEMENT.md`.

1. Work in the task's worktree `../closet-wt/$1`.
2. Run `python3 .claude/scripts/check_scopes.py --diff $1` (must print OK) (stage 2: check `external_actions` for `$1` in Postgres).
3. Invoke `test-runner` with the done-check and any previous results from the registry.
4. Update the registry row's Status to Verified or Failed, with the test report path.
