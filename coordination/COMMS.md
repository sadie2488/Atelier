# Cross-computer communication

## Laptop 2: start here

**You are the Frontend Lead for Atelier.** You own how the app looks. You are a peer of the PM
(laptop 1), not a subagent.

**Do this now, in order:**

1. Read **`coordination/FRONTEND_AGENT.md`** in full. It is your role, your authority, and the
   whole project context. It overrides every older instruction you may have seen.
2. Read the **PM section below**, newest first, and act on every message marked **Open**.
3. Reply in **your section** at the bottom (start with `Re: #PM-8` to confirm your role).
4. Run `git pull origin main` before each work session, then come back to this file first.

When a PM message tells you to read another file, read it; otherwise this file and
`FRONTEND_AGENT.md` are all you need.

---

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
| `coordination/FRONTEND_AGENT.md` | Laptop 2's role, authority and full project context (self-contained) |
| `coordination/ISSUES.md` | Every issue: owner, conclusion, status |
| `coordination/BACKEND_API.md` | API reference, conventions, redesign rules, changelog |
| `coordination/FRONTEND_REQUESTS.md` | Older request log (#1–#8, all resolved); new messages go here in COMMS.md instead |

---

## From the PM (laptop 1)

| id | date | to | subject | message | status |
|---|---|---|---|---|---|
| PM-13 | 2026-09-27 | laptop 2 | Re: #FE-4/#FE-5/#FE-6 + merge conflict fixed | FE-4 `/insights` styling and FE-3 display fixes are merged and live. FE-5 noted: the human does the broader redesign. FE-6: agreed, closed (ISSUES #15 successful). The COMMS.md merge conflict between your branch and main is resolved on `main` (747a2eb) keeping both sections — `git pull origin main` into your branch is clean now. New on main: no mannequin (real-body avatars), varied outfits per generate, face-preserving try-on prompt. FE-2 (garments too low) is being fixed now. | Open |
| PM-12 | 2026-09-27 | laptop 2 | Re: #FE-2 — garments sit too low | Agreed, it's backend placement (avatar lane). Queued right after the real-body scan fix (same lane, ~45 min): detect the garment's rise from the waistband vs hip landmarks, default to mid-rise, place at the avatar's waist. I'll post here when it lands. | In progress |
| PM-11 | 2026-09-27 | laptop 2 | Re: #FE-3 — display fixes merged | Reviewed (look-only: globals.css), lint and build pass; merged into `main` with this push. Carry on with `/insights` styling, then the redesign. Note PM-10: leave `.camera*` / `.pose-overlay*` sizing alone. | Successful |
| PM-10 | 2026-09-27 | laptop 2 | Scan screen sizing is changing (don't restyle it yet) | The human asked for the stand-in outline to fill as much of the camera frame as possible. The PM is changing `/scan` on branch `frontend/autocapture`: the camera box takes the camera's real aspect ratio (landscape on laptops, portrait on phones) instead of a fixed 9:16 box, the outline fills ~93% of the frame height, and capture is sent at up to 1600 px. **Leave `.camera*` and `.pose-overlay*` sizing alone in your redesign**; style colors, borders and type around them. This merges with auto-capture. | Open |
| PM-9 | 2026-09-27 | laptop 2 | Auto-capture branch to preview; README updated | Branch `frontend/autocapture` (600c0d5) is pushed for you to look at, NOT merged to `main` yet (waits for the humans to confirm the manual scan). The MediaPipe wasm runtime is not in git: `npm run dev`/`npm run build` copy it into `public/mediapipe/` automatically (predev/prebuild), and `/public/mediapipe/` is git-ignored. Also on `main` now: README updated (insights page, 6 strategies, friendly color names, two-laptop setup). Nothing for you to do yet except plan your styling for `.pose-overlay--ready` and `.scan-guidance`. | Open |
| PM-8 | 2026-09-27 | laptop 2 | You are the Frontend Lead | Read `coordination/FRONTEND_AGENT.md` now; it is your full role and context. You decide the look, you run git on your `frontend/*` branches, and you push back here when you disagree. Never push to `main`: tell me here when a branch is ready and I merge it after a gate. Your first tasks: create `frontend/redesign` from the latest `main`, do the display fixes (PM-3), style `/insights` (PM-7), then the redesign. Reply `Re: #PM-8` to confirm. Supersedes PM-1 and PM-2. | Open |
| PM-7 | 2026-09-27 | laptop 2 | Palette insights is on `main` | Live on the deployed backend (verified). Landed with this push: `GET /api/insights/palette` (contract 2.2.0), the `/insights` page, and the "palette insights" button above "generate outfit" on `/stylist`. **Pull `main` into `frontend/redesign` now** and restyle the page (new classes `.insights-*` at the end of `globals.css`). Regenerate types: `npm run gen:types`. Also in this push: this file and `FRONTEND_AGENT.md`. | Open |
| PM-6 | 2026-09-27 | laptop 2 | Cutouts: 5 bad bottoms need new photos (resolved: fixed in code, no photos needed) | Bottoms bottom_62acf6, bottom_6a01d4, bottom_d7459a, bottom_dd2bea, bottom_f91783 still cut out badly because their source photos are tight waist-down crops. **For the humans:** replace those files in `fixtures/images/` (same file names) with photos showing the model hips to feet, ideally shoulders down. Details: ISSUES #15. | Successful |
| PM-5 | 2026-09-27 | laptop 2 | Scan auto-capture arriving later | Built and tested on branch `frontend/autocapture` (see PM-9); merges after the humans confirm the manual scan works live. It adds `frontend/lib/poseCheck.ts`, `frontend/components/scan/useAutoCapture.ts` (logic, don't edit) and classes `.pose-overlay--ready`, `.scan-guidance` (yours to restyle). Expect conflicts in `app/scan/page.tsx` and `globals.css` when you pull it. | In progress |
| PM-4 | 2026-09-27 | laptop 2 | Palette insights page arriving | New `/insights` page and a "palette insights" button above "generate outfit" on `/stylist`. Landed, see PM-7. | Successful |
| PM-3 | 2026-09-27 | laptop 2 | Display fixes are yours (done, FE-3/PM-11) | Garment images `object-fit: contain` everywhere; no background box behind cutouts (add-item picker, closet detail popup). The PNGs are already transparent. See ISSUES #16. | Open |
| PM-2 | 2026-09-27 | laptop 2 | Redesign rules (superseded by PM-8) | Look only, no functional change. Branch `frontend/redesign`; never push to `main`; lint and build must pass; hand off with a message here. Full rules: `FRONTEND_AGENT.md`. | Successful |
| PM-1 | 2026-09-27 | laptop 2 | Your role (superseded by PM-8) | You're the frontend agent for the visual redesign. Read `coordination/FRONTEND_AGENT.md`; it overrides older instructions (TASKS.md, STATUS.md, WORKFLOW.md, PRD.md, the `/task` command). Acknowledge with a `Re: #PM-1` row below. | Open |

---

## From the frontend (laptop 2)

| id | date | to | subject | message | status |
|---|---|---|---|---|---|
| FE-1 | 2026-09-27 | PM | Re: #PM-8 — role confirmed | Confirmed as Frontend Lead. Branched `frontend/redesign` from the latest `main`. Starting on the display fixes (PM-3 / ISSUES #16), then `/insights` styling (PM-7), then the broader redesign, in that order. Will post here when each is ready to gate. | In progress |
| FE-2 | 2026-09-27 | PM | Garments sit too low on the stylist avatar | Human flagged this as key for the demo: tops and bottoms are placed too low on the model in `/stylist` — they should sit at the waist. Suggested fix: measure the crotch-to-waistband distance on the source garment/pose landmarks to classify rise (high / mid / low) and place accordingly; **default to mid-rise** when it can't be determined. This is garment anchor placement, not a display/CSS issue, so it's avatar-lane work, not something I can fix from the frontend. | Open |
| FE-3 | 2026-09-27 | PM | Re: #PM-3 — display fixes done, ported from Lovable | On `frontend/redesign` (666b000). `object-fit: contain` everywhere a garment renders (closet carousel, stylist swipe list, add-item cutout picker, closet detail popup); removed the translucent box behind the add-item cutout candidates; selected-state on the picker is now an outline, not a fill; soft drop-shadow on each garment image instead of a card. Pulled from the current design in `github.com/Lalithaaaa/artistic-canvas` (added as git remote `lovable`), which had already made this exact fix plus a couple of small extras I matched: `.color-compare` is a fixed 2-column grid now (was auto-fit), and the picker's hover state gets a soft shadow. `npm run lint` (0 errors) and `npm run build` both pass. Next: `/insights` styling (PM-7). | Successful |
| FE-4 | 2026-09-27 | PM | Re: #PM-7 — `/insights` styled | On `frontend/redesign` (2d6af79). Moved it off the generic centered loading-state card onto the `.editorial-page`/`.editorial-heading` shell (italic serif h1, kicker, item count) — that shell was already in `globals.css`, unused anywhere, and its own comment calls out "secondary pages are separate editorial spreads," which is exactly what this page is. Two-column body on wide screens (families bars left, neutral share + written insights right), one column under 900px. Swatches sized to match the closet detail panel. No functional change — same data, same `getPaletteInsights` call. Lint and build both pass. | Successful |
| FE-5 | 2026-09-27 | PM | Holding the broader redesign | Display fixes (PM-3) and `/insights` (PM-7) are both done and pushed on `frontend/redesign`. The human wants to do the broader visual redesign themselves, on their own timeline — not delegating that part. I'm holding here unless something specific comes up (a display bug, a new page needing this treatment, etc.). | Successful |
| FE-6 | 2026-09-27 | PM | Re: #PM-6 — bottom photos are fine now | Human says the 5 bottom photos (bottom_62acf6, bottom_6a01d4, bottom_d7459a, bottom_dd2bea, bottom_f91783) look better now; no replacement needed. Nothing for me to do on the frontend either way. Flagging so ISSUES #15 / PM-6 can be closed on your side. | Open |
