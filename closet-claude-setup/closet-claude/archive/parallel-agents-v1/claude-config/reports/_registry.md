# Report Registry

**Last Updated:** 2026-09-26 (Phase 0: setup)

> **Purpose:** Central index of agent work. Main agents check here before every dispatch.
> **Rule:** each lane's architect edits only its own section. The Shared section is edited by the human integrator.
> Task history lives in `.claude/tasks/<ID>/` (ANNOUNCEMENT.md + REPLY.md); run `announce.py --status` for live state.

---

## Shared (human integrator only)

| Report | Task | Date | Status | Summary |
|--------|------|------|--------|---------|
| [PRD.md](../../PRD.md) | — | 2026-09-26 | Active | Product requirements: four-step demo flow, stack, lanes, phases, risks. |

**Contract status:** Not frozen (`announce.py` checks for `contract/FROZEN` in main).

**Remote:** origin/main on GitHub. Humans push after every merge and pull before announcing (see WORKFLOW.md).

**Dry run:** Not run (TA00 / TB00).

**Logging:** Stage 1 (local queue). Stage 2 = Postgres; see WORKFLOW.md.

**Rung status:**

| Rung | Status | Date | Notes |
|------|--------|------|-------|
| 1 | Not started | | |
| 2 | Not started | | |
| 3 | Not started | | |

**Open handoff requests:**

_None yet_

---

## Lane A: Scan & avatar

| Report | Task | Date | Status | Summary |
|--------|------|------|--------|---------|

_Add Lane A rows here_

---

## Lane B: Recommend & render

| Report | Task | Date | Status | Summary |
|--------|------|------|--------|---------|

_Add Lane B rows here_

---

**Status values:** Announced | Replied | Verified | Merged | Blocked | Failed
