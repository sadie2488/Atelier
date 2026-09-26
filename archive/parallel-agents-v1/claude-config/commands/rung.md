---
description: Prepare a rung merge for this lane - review every verified branch and hand the human a merge list
argument-hint: <rung number 1|2|3>
---

# Rung

Prepare Rung **$1** for this lane, following "Rung merges" in the `architect` skill.

1. List every task for this lane and rung (see PRD.md Section 8 and `announce.py --status`) and confirm each is Verified in the registry. Stop and list any that aren't.
2. Run `/review` on each branch.
3. Give the human a merge list: branch, verdict, report path, in dependency order. Do not merge.
4. After the human confirms the merge, dispatch `test-runner` on the merged result against the rung's check from PRD.md, and record the result in the registry.
