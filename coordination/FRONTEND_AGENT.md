# Laptop 2: Frontend Lead — role and full context

**Written by the PM (laptop 1), 2026-09-27. This file is self-contained: it is everything laptop 2
needs.** It overrides every older instruction outside `coordination/` (TASKS.md, STATUS.md,
WORKFLOW.md, PRD.md, the `/task` command, older FRONTEND_REQUESTS rows). Laptop 2 reads only the
`coordination/` folder.

Read order after every `git pull`: **1. `COMMS.md`** (messages) → **2. this file** →
**3. `ISSUES.md`** (status of every issue) → **4. `BACKEND_API.md`** (full endpoint detail, only
when you need it).

---

## 1. Your role and authority

You are the **Frontend Lead**: a peer of the PM, not a subagent.

**You decide:**
- Everything about how the app looks and feels: visual design, layout, typography, color,
  motion, component structure and naming, copy and microcopy on screen.
- How to organize the frontend code you change, what to refactor for the redesign, and in what
  order.
- Whether a PM request makes sense for the UI. Push back in `COMMS.md` with your reasoning when
  it doesn't; the humans settle disagreements.

**You may:**
- Run git freely on your own branches (`frontend/*`): branch, commit, merge `main` into your
  branch, push your branches.
- Run the backend locally for testing, and read any file in the repo.
- Ask the PM for backend or API changes (a message in `COMMS.md`); the PM builds them.

**Shared guardrails (they protect the live demo, not your authority):**
- **Never push to `main`.** `main` auto-deploys the live site. The PM merges your branch after
  a gate (lint, build, the whole flow against the real backend).
- **Functionality stays as it is** unless the humans ask for a change. See section 5.
- Never read or print `.env` files or secrets. Never force-push, rebase shared branches, or
  `reset --hard`.
- No emojis in the UI. No mention of AI tools as authors in commits or PRs.

**Deadline rule:** once the humans start rehearsing the demo, stop merging redesign work. A
half-finished look is worse than the current one.

## 2. The project in one page

**Atelier** is a hackathon wardrobe app. A user:

1. **Scans themselves**: a front-facing, full-body photo. The backend checks the pose (and says
   exactly what to fix if not), then cuts the person's real body out of the photo as their
   avatar.
2. **Adds garments** from retail photos of a model wearing the item. The backend finds the
   garment using body pose and segmentation, offers **3 cutout candidates** (tight / balanced /
   generous), and the user picks one. Its color is measured in Lab color space, with a friendly
   name ("evergreen", "dark maroon").
3. **Generates outfits**: a deterministic color-theory scorer with 6 strategies (neutral anchor,
   everyday-neutral base, analogous, complementary, monochrome + highlight, sandwich) returns up
   to 5 ranked outfits, each with a one-line explanation.
4. **Sees it on themselves**: an instant local composite of the garments on their avatar, then
   a Gemini-generated try-on (~12 s) that is color-checked and swapped in silently.
5. **Palette insights**: a closet-wide color summary (MongoDB aggregation).

**Stack:** Next.js (App Router) + TypeScript + Tailwind on **Vercel** · FastAPI (Python 3.12) +
MediaPipe on **DigitalOcean App Platform** (Docker) · **MongoDB Atlas** (items, avatars, renders;
all images in GridFS) · **Google Gemini** (try-on images, outfit explanations).

**Live URLs:** backend `https://atelier-9t24w.ondigitalocean.app` (`/api/live`, `/api/health`).
The frontend on Vercel proxies `/api/*` and `/media/*` to it (`BACKEND_URL` in Vercel).

## 3. Frontend map

```
frontend/
├── app/
│   ├── page.tsx            home
│   ├── closet/page.tsx     closet carousel by category + item detail popup (color swatches)
│   ├── scan/page.tsx       consent → camera + pose outline → countdown → capture → avatar
│   ├── add-item/page.tsx   upload → category/garment type → pick 1 of 3 cutouts → save
│   ├── stylist/page.tsx    swipe tops/bottoms/jackets, "generate outfit", "see it on me",
│   │                       "palette insights" button, two-stage render
│   ├── insights/page.tsx   "Your palette": swatches, family bars, neutral share, insights
│   ├── globals.css         all styling (insights styles at the end, `.insights-*`)
│   └── layout.tsx
├── components/             Button, HangerMenu, HealthDot, PoseFigure, StatePanel, closet/*, icons
└── lib/
    ├── api.ts              typed API client (every backend call lives here)
    ├── api-types.ts        GENERATED from contract/schema.json: `npm run gen:types`
    └── hooks.ts            data hooks (e.g. useItems)
```

**This Next.js version has breaking changes** from what you were trained on. Before writing
Next-specific code (routing, `Link`, `Image`, config, data fetching), read the relevant guide
in `frontend/node_modules/next/dist/docs/`.

**Run it:** `cd frontend && npm ci && npm run dev` (http://localhost:3000). To use the live
backend, put `BACKEND_URL=https://atelier-9t24w.ondigitalocean.app` in `frontend/.env.local`.
Before hand-off: `npm run lint` and `npm run build` must pass.

## 4. The API (summary; full detail in `BACKEND_API.md`)

All under `/api`, JSON unless noted. Errors are always
`{"error": {"code": "...", "message": "..."}}`.

| Method | Path | Returns / notes |
|---|---|---|
| GET | `/health` | `{"status":"ok","db":"ok"}` |
| POST | `/items/analyze` | multipart: `image`, `category` (tops/bottoms/jackets), `garment_type`, optional `color`, `item_name` → `temp_handle` + exactly 3 candidates (cutout_url, primary/secondary color). Saves nothing. ~1–3 s |
| POST | `/items/save` | `{temp_handle, candidate_index}` → the saved Item |
| POST | `/items/reject` | `{temp_handle}` → `{"ok": true}` |
| GET | `/items` | closet, newest first; `?category=` filter |
| GET | `/items/{id}` | one Item |
| POST | `/outfits/generate` | `{}` or `{"limit": 1-5}` → up to 5 outfits: `outfit_id`, `strategy`, `top_id`, `bottom_id`, `jacket_id`, `explanation`, `score` 0–1 |
| POST | `/avatar/scan` | multipart `image` → `{avatar_id, wireframe_url, avatar_url}`, or 422 `pose_rejected` whose message has **one reason per line** |
| GET | `/avatar/{avatar_id}` | one avatar |
| POST | `/render` | `{avatar_id, top_id, bottom_id, jacket_id?}` → `{render_id, status, local_url, generated_url?}` |
| GET | `/render/{render_id}` | poll: `pending` → `done` (+ `generated_url`) or `failed` (keep local) |
| GET | `/insights/palette` | item_count, neutral_share, families [{family, count, share, hex}], swatches, missing_families, insights (sentences), most_versatile |

**Data shapes worth knowing:**
- Item: `id` (like `top_9a92f8`, `dress_…`, `bottom_…`, `jacket_…`), `category`, `garment_type`,
  `cutout_url` (`/media/items/<id>.png`, transparent PNG), `primary_color`, `secondary_color`,
  `retailer_item_name`.
- Color: `hex`, `display_name` (show this; fall back to `name`), `name`/`family` (coarse styling
  categories), `is_neutral`.
- A **dress is a top**: it lives in the tops list and layers over a bottom.

## 5. Behaviors that must not change

- **Rendering happens only from the "see it on me" button and right after "generate outfit".**
  Never on swipe or selection. Each new combination costs a paid Gemini call.
- **Two-stage render:** show `local_url` at once; poll `GET /api/render/{id}` every 1 s for
  15 s, then every 3 s, giving up at 45 s; swap `generated_url` in silently; **no error toast
  when a render fails** (the local image stays).
- **"Generate outfit" positions, it doesn't filter:** it moves the top outfit's garments to the
  front of the tops and bottoms lists; the user keeps swiping freely.
- **Scan:** the consent notice ("your photo is sent to Google's Gemini API") before the camera;
  the countdown; the backup-avatar button and `/scan?backup=<avatar_id>`; one bullet per line of
  a rejection message; a big "Try again".
- **Every failure shows a calm, visible state**: no blank screens, no stack traces, no hanging
  spinners.
- **Relative URLs only** (`/api/...`, `/media/...`).
- **No new npm packages** without asking in `COMMS.md` (fonts via CSS are fine).

## 6. What's yours right now

1. **The visual redesign** (look only), on branch **`frontend/redesign`** from the latest `main`.
2. **Display fixes:** garment images use `object-fit: contain` everywhere (closet tiles, stylist
   swipe list, add-item picker), never `cover`; no background box behind cutouts (add-item
   `.cutout-img`, closet detail popup). The PNGs are already transparent (ISSUES #16).
3. **Style the new `/insights` page** (it's on `main` now; pull it into your branch).

**Arriving from the PM (plan for it, don't rebuild it):** scan **auto-capture**, a live in-browser
pose check that turns the outline green and starts the countdown by itself. It adds
`frontend/lib/poseCheck.ts` and `frontend/components/scan/useAutoCapture.ts` (logic; leave these
alone) plus classes `.pose-overlay--ready` and `.scan-guidance` (yours to style). It merges after
the humans confirm the manual scan works live. Expect conflicts in `app/scan/page.tsx` and
`globals.css`: keep its logic, apply your styling.

## 7. Hand-off

1. `npm run lint` and `npm run build` pass; you've clicked through every page against a running
   backend (local or live).
2. Push your branch (`git push origin frontend/redesign`).
3. Post in `COMMS.md` (your section): "redesign checkpoint ready on frontend/redesign at
   <commit>", with what changed and anything the PM should check.
4. The PM reviews, gates and merges to `main`, and answers in `COMMS.md`.

## 8. Handy facts

- Backup avatar: `avatar_f709dc` (Sadie); alternative `avatar_56501c` (Lalitha). Outfits with
  cached try-ons (instant): `dress_6b8577 + bottom_f91783` (with or without `jacket_18d0da`),
  `top_9a92f8 + bottom_e7883c`.
- 19 closet items; list them at `/api/items`.
- Known limitations (accepted): striped garments report their base color as primary; light-wash
  denim can read as gray; 5 bottoms have poor cutouts until the humans replace their photos
  (ISSUES #15).
