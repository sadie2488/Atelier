---
description: Announce and dispatch one task (from TASKS.md or an existing draft) to its expert
argument-hint: <task-id>
---

# Dispatch

Architect steps 2–3 for task **$1** (see the `architect` skill):

1. If `.claude/tasks/_drafts/$1.md` doesn't exist, run `python3 .claude/scripts/announce.py --from-tasks $1`.
2. Fill in every `[ARCHITECT: ...]` placeholder in the draft.
3. Run `python3 .claude/scripts/announce.py --draft .claude/tasks/_drafts/$1.md`. If it refuses, report why and stop.
4. Dispatch the expert exactly as `announce.py` printed (cwd pinned to the worktree, in the background).
5. When the expert returns, run `/collect $1`.
