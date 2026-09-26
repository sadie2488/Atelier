---
description: Work on one task from TASKS.md, then report what changed and the check result
argument-hint: <task-id, e.g. A1 or B2>
---

# Task $1

1. Read only the `### $1` section of `TASKS.md` (for example `grep -n -A 20 "^### $1 " TASKS.md`), plus the files it names. If it's marked ⇄, confirm with your human that the dependency is merged and pulled.
2. Say in 3–5 lines what you'll build and which files you'll touch. Stay inside the task's files and your lane's folders (see `CLAUDE.md`).
3. Implement it. Build against `contract/` and, for the scorer, `SCORER.md`. Install only the dependencies the task lists.
4. Run the task's **check**. Fix failures in your own files only; build errors in files you didn't edit follow the wait-and-retry rule in `CLAUDE.md`.
5. Report: files changed, the last lines of the check output, a suggested commit message, and anything the other lane needs to know. Don't push or merge.