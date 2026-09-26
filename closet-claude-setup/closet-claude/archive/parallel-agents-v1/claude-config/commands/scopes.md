---
description: Check agent scopes for overlaps, or check whether tasks can run in parallel
argument-hint: [task-id ...]
---

# Scopes

- No arguments: run `python3 .claude/scripts/check_scopes.py` and report every WARN or ERROR. Any overlap between agents' scopes must be fixed by a human in `.claude/scopes.json` before dispatching more work.
- With task IDs: run `python3 .claude/scripts/check_scopes.py --tasks $ARGUMENTS` and say plainly whether they can run in parallel. Any WARN means run them one after another.
