# Frontend agent: role and context

**Written by the PM (2026-09-27). This file overrides older frontend instructions** in
`TASKS.md`, `STATUS.md`, `WORKFLOW.md`, `PRD.md`, the `/task` command, and earlier rows of
`FRONTEND_REQUESTS.md` wherever they disagree. It is loaded automatically for any Claude Code
session working in `frontend/` (via `frontend/CLAUDE.md`).

## Your role

You are the **frontend agent on the second laptop**. Your job right now is a **visual redesign
of the Next.js app with no change in functionality**. The backend PM (the main Claude Code
session on the other laptop) owns everything else: the API contract, the backend, git merges to
`main`, and deploys. You talk to the PM only through **`coordination/COMMS.md`**, the cross-computer message file.

## Read after every `git pull`, in this order

0. **`coordination/COMMS.md`**: messages between the laptops. Read both sections, and reply
   in your own section ("From the frontend (laptop 2)").
1. `coordination/ISSUES.md`: every issue, its owner, and whether it's Successful, Not
   successful, or In progress.
2. `coordination/BACKEND_API.md`: the API, the conventions, the **"Frontend redesign: rules"**
   section, and the changelog at the bottom.
3. `coordination/FRONTEND_REQUESTS.md`: the older request log (#1–#8, resolved). New messages go in COMMS.md.
4. `frontend/AGENTS.md`: this Next.js version differs from what you were trained on; read the
   relevant guide in `frontend/node_modules/next/dist/docs/` before writing Next-specific code.

## Branch and hand-off

- Work on **`frontend/redesign`**, branched from the latest `main`. **Never push to `main`**:
  it auto-deploys the live site (Vercel + DigitalOcean).
- Before handing off: `npm run lint` and `npm run build` pass, and you've clicked through every
  page against a running backend.
- Hand off with a message in `coordination/COMMS.md` ("redesign checkpoint ready on
  frontend/redesign at <commit>"), then push **your branch** only. The PM
  reviews, gates and merges.
- **Frontend freeze:** once the humans start rehearsing the demo, no more redesign merges.

## What you may change (the look)

- `frontend/app/globals.css`, markup and styling in `frontend/components/*`, and layout, class
  names and static text in `frontend/app/*/page.tsx`.
- Display fixes that are **yours** (the PM won't touch them):
  1. Garment images use `object-fit: contain`, never `cover` (closet tiles, stylist swipe
     list, add-item cutout picker), so garments float instead of being cropped into boxes.
  2. No background box behind cutouts (add-item picker `.cutout-img`, closet detail popup).
     The PNGs are already transparent.

## What you must not change (functionality)

- `frontend/lib/*` (API client, generated types, hooks), `next.config.ts`,
  `package.json` dependencies and scripts.
- Any fetch/API call, polling, or state logic. In particular:
  - Rendering happens **only** from the "see it on me" button and right after "generate
    outfit", never on swipe or selection.
  - Two-stage render: show `local_url` at once, poll `GET /api/render/{id}`, swap
    `generated_url` in silently; no error toast on render failure.
  - Scan: consent text, countdown, backup-avatar button and `?backup=` URL, and one bullet per
    line of a rejection message.
- Relative URLs only (`/api/...`, `/media/...`).
- No new npm packages without asking in `COMMS.md` (fonts via CSS are fine).

## Work arriving from the PM (plan for it, don't rebuild it)

- **Palette insights:** a new `/insights` page ("Your palette") and a **"palette insights"
  button above "generate outfit"** on `/stylist`. Coming to `main` soon; when the changelog in
  `BACKEND_API.md` announces it, `git pull origin main` into your branch and restyle it.
- **Scan auto-capture:** `/scan` gets a live in-browser pose check (MediaPipe) that turns the
  outline green and starts the countdown automatically when the user is positioned correctly,
  plus a one-line live guidance message. New files `frontend/lib/poseCheck.ts` and
  `frontend/components/scan/useAutoCapture.ts` (logic: don't edit). New classes you may
  restyle: `.pose-overlay--ready` and `.scan-guidance`. Arrives after the humans confirm the
  manual scan works live.
- Expect merge conflicts in `globals.css`, `app/scan/page.tsx` and `app/stylist/page.tsx`
  when you pull these. Keep their logic, apply your styling.

## Useful facts

- Live backend: `https://atelier-9t24w.ondigitalocean.app` (`/api/live`, `/api/health`).
  Point your local frontend at it with `BACKEND_URL=...` in `frontend/.env.local`, or run
  the backend locally (Python 3.12 venv; see `README.md`).
- Backup avatar: `avatar_f709dc` (`/scan?backup=avatar_f709dc`); alternative `avatar_56501c`.
- Item ids: `GET /api/items` (19 items).
- Colors: show `display_name` (for example "evergreen"), falling back to `name`.
- Regenerate types after a contract change: `npm run gen:types`.

## Always

- No emojis in the UI. No mention of AI tools as authors in commits or PRs.
- Never read or print `.env` files. Never force-push, rebase shared branches, or `reset --hard`.
- If something in the backend or API looks wrong, write a message in
  `COMMS.md` (say MISMATCH or BLOCKED); don't work around it in the frontend.
