---
description: Collect an expert's finished work - scope check, commit on the task branch, then review
argument-hint: <task-id>
---

# Collect

1. Run `python3 .claude/scripts/announce.py --collect $1`. If it refuses, report the scope errors and stop.
2. Read `../closet-wt/$1/.claude/tasks/$1/REPLY.md`.
3. Re-run the check printed by collect yourself and compare it with the REPLY's pasted output. For frontend tasks, look at the screenshots in `evidence/`.
4. Follow steps 5–6 of the `architect` skill: review, report, give the human the merge and push commands, update the registry.
