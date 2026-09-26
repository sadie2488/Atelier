---
description: Run the workflow dry run (TA00 on laptop A, TB00 on laptop B) - see WORKFLOW.md
---

# Dry run

Follow "Dry run" in `WORKFLOW.md` for this laptop's lane (`.claude/lane.local`):

1. Copy `.claude/tasks/_templates/dryrun/T<LANE>00.md` to `.claude/tasks/_drafts/T<LANE>00.md`.
2. `python3 .claude/scripts/announce.py --draft .claude/tasks/_drafts/T<LANE>00.md`. On laptop B this must refuse until laptop A has merged and pushed TA00 and laptop B has pulled; report the refusal, that's part of the test.
3. Dispatch the expert exactly as printed, then `/collect`, re-run the check, and give the human the merge and push commands.
4. Run the three guard probes in `WORKFLOW.md` and report each result.
