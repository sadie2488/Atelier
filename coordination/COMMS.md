# Cross-computer communication

**The one file both laptops read first, after every `git pull`.** It links to everything else.

- **Laptop 1 = PM** (backend, contract, merges and deploys).
- **Laptop 2 = frontend agent** (visual redesign). Its role: `coordination/FRONTEND_AGENT.md`.

## How to use it

1. After every pull, read **both sections below**, newest first. Act on anything addressed to you.
2. To send a message, add a row at the **top of your own section only**. Never edit the other
   side's section, so git merges both sides cleanly.
3. To answer a message, add a new row in your section that starts with `Re: #<id>`, and set its
   status. The sender updates the status of their original row when it's resolved.
4. **Status** is one of: **Open** (needs a response), **In progress**, **Successful**,
   **Not successful** (with the reason).
5. Message ids: `PM-<n>` for laptop 1, `FE-<n>` for laptop 2.

## Reference (read when a message points you there)

| File | What |
|---|---|
| `coordination/FRONTEND_AGENT.md` | Laptop 2's role, rules, and what it may and may not change |
| `coordination/ISSUES.md` | Every issue: owner, conclusion, status |
| `coordination/BACKEND_API.md` | API reference, conventions, redesign rules, changelog |
| `coordination/FRONTEND_REQUESTS.md` | Older request log (#1–#8, all resolved); new messages go here in COMMS.md instead |

---

## From the PM (laptop 1)

| id | date | to | subject | message | status |
|---|---|---|---|---|---|
| PM-7 | 2026-09-27 | laptop 2 | Palette insights is on `main` | Landed with this push: `GET /api/insights/palette` (contract 2.2.0), the `/insights` page, and the "palette insights" button above "generate outfit" on `/stylist`. **Pull `main` into `frontend/redesign` now** and restyle the page (new classes `.insights-*` at the end of `globals.css`). Regenerate types: `npm run gen:types`. Also in this push: this file and `FRONTEND_AGENT.md`. | Open |
| PM-6 | 2026-09-27 | laptop 2 | Cutouts: 5 bad bottoms need new photos | Bottoms bottom_62acf6, bottom_6a01d4, bottom_d7459a, bottom_dd2bea, bottom_f91783 still cut out badly because their source photos are tight waist-down crops. **For the humans:** replace those files in `fixtures/images/` (same file names) with photos showing the model hips to feet, ideally shoulders down. Details: ISSUES #15. | Open |
| PM-5 | 2026-09-27 | laptop 2 | Scan auto-capture arriving later | Built and tested on branch `frontend/autocapture`; merges after the humans confirm the manual scan works live. It adds `frontend/lib/poseCheck.ts`, `frontend/components/scan/useAutoCapture.ts` (logic, don't edit) and classes `.pose-overlay--ready`, `.scan-guidance` (yours to restyle). Expect conflicts in `app/scan/page.tsx` and `globals.css` when you pull it. | In progress |
| PM-4 | 2026-09-27 | laptop 2 | Palette insights page arriving | New `/insights` page and a "palette insights" button above "generate outfit" on `/stylist`. Landed, see PM-7. | Successful |
| PM-3 | 2026-09-27 | laptop 2 | Display fixes are yours | Garment images `object-fit: contain` everywhere; no background box behind cutouts (add-item picker, closet detail popup). The PNGs are already transparent. See ISSUES #16. | Open |
| PM-2 | 2026-09-27 | laptop 2 | Redesign rules | Look only, no functional change. Branch `frontend/redesign`; never push to `main`; lint and build must pass; hand off with a message here. Full rules: `FRONTEND_AGENT.md`. | Open |
| PM-1 | 2026-09-27 | laptop 2 | Your role | You're the frontend agent for the visual redesign. Read `coordination/FRONTEND_AGENT.md`; it overrides older instructions (TASKS.md, STATUS.md, WORKFLOW.md, PRD.md, the `/task` command). Acknowledge with a `Re: #PM-1` row below. | Open |

---

## From the frontend (laptop 2)

| id | date | to | subject | message | status |
|---|---|---|---|---|---|
| | | | | *(add your first message here, e.g. `Re: #PM-1` to acknowledge)* | |
