---
description: Pre-merge review of a task branch with the code-reviewer agent
allowed-tools: Bash(git:*)
argument-hint: <branch or task-id>
---

# Review

Dispatch `code-reviewer` for **$1**.

1. Resolve the branch (`agent/<lane>-<task-id>`) and look up its allowlist in `.claude/tasks/<task-id>/ANNOUNCEMENT.md`.
2. Gather `git diff main...<branch> --stat`, the task's ANNOUNCEMENT.md and REPLY.md, the test report, `check_scopes.py --diff <task-id>` output, and (stage 2) the `external_actions` rows for the task.
3. Invoke `code-reviewer` with all of the above and the relevant contract excerpt.
4. Report the verdict (MERGE / FIX FIRST / REJECT), the review report path, and the manual merge commands to the human. Never merge.
