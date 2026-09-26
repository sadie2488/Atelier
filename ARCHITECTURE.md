# Atelier — Architecture

Shared reference for everyone working on this project: the backend PM, the three lane
subagents, and the frontend. Read this first; it explains how the pieces fit. The detail lives
elsewhere and is linked from here.

**Atelier** is a wardrobe app. Garments are ingested from retail product images, cut off the
model, and stored with a numeric color. The user browses their closet, generates an outfit
recommendation from color theory, and sees it rendered on an avatar built from their own scan.

---

## Deployment chain

```
browser → Vercel (Next.js frontend) → DigitalOcean App Platform (FastAPI) → MongoDB Atlas
                                              ↓
                                      Gemini (explanations, generated try-on)
```

`next.config.ts` rewrites `/api/*` and `/media/*` to the backend. `BACKEND_URL` has no trailing
slash and no `/api` — the rewrite adds the path. Both apps redeploy on every push to `main`,
which is why the PM's push gate exists.

All backend routes live under `/api`. `/media` stays at the top level.

---

## The five invariants

Break any of these and something fails quietly, usually in production rather than locally.

1. **Media URLs are always relative** (`/media/...`). An absolute URL embeds a host, works on
   localhost, and breaks behind the Vercel rewrite.
2. **Colors are numeric.** Lab values everywhere. Names are derived by lookup from
   `contract/colors.json`, never stored as truth. `is_neutral` is computed from chroma, and
   where a name lookup and chroma disagree, **chroma wins**.
3. **The scorer is pure.** No I/O inside scoring functions. Same inputs, same score.
4. **The local composite always works.** Generated try-on is an enhancement layer that may fail
   silently at any time.
5. **A dress is a top.** `category: tops`, layered over a bottom. Only `garment_type: dress`
   differs, and only vision reads it — for segmentation region selection.

---

## Backend lanes

Three subagents with disjoint file ownership, running concurrently in one working tree. They
never import from each other; they meet only at the frozen contract.

| Lane | Owns | Produces |
|---|---|---|
| **vision** | `backend/vision/**`, `routes/items.py` | Saved items: transparent cutout + Lab color + flags |
| **styling** | `backend/styling/**`, `routes/outfits.py` | Ranked outfits: garment ids + strategy label |
| **avatar** | `backend/avatar/**`, `routes/avatar.py` | Rendered images of outfits on the user's avatar |

The PM (main Claude Code session) owns everything shared: `contract/`, `main.py`, `db.py`,
`config.py`, `requirements.txt`, the agent definitions, and the scope guard. Only the PM runs
git.

`main.py` registers all three routers in Phase 0 against stubs and is **never edited again** —
that is what lets three agents write concurrently without colliding.

---

## Data flow

### Ingest — two steps, nothing persists until the second

```
retail image + category + garment_type + retailer color/name
  → normalize → segment garment off the model → 3 candidate cutouts
  → user picks one → extract Lab color → save with slug id (top_a3f9c2)
```

Rejecting all three persists nothing, logs the failure, and restarts from a fresh capture.

### Recommend

```
items → pairwise harmony scores → strategies generate outfits
      → rank, apply diversity caps → top 5 with strategy labels
```

The result is a **positioning instruction**, not a view: the frontend moves the top-ranked
outfit's garments to index 0 of the swipe lists. Browsing itself never consults the scorer.

### Render — two stages

```
POST /api/render → local composite returned immediately + render_id
                 → generation runs in background
GET  /api/render/{id} → poll → done (swap in) | failed (keep local)
```

The `render_id` doubles as the cache key — `(user_id, top_id, bottom_id, jacket_id)` — stored
in Mongo so it survives container restarts. A repeat combination returns `done` on the first
call with no generation at all.

---

## Frontend / backend split

**Frontend:** camera capture and pose outline, client-side downscaling, swipe lists, the
generate button, index-0 positioning, the metadata detail panel, polling and image swapping,
all loading and degraded states.

**Backend:** every endpoint, segmentation, color extraction, scoring, outfit selection, avatar
assembly, compositing, generation, caching, all media files.

**Never duplicated across the boundary:** color logic, scoring logic, garment placement. If
either side finds itself writing these, it is on the wrong side of the line — raise it.

---

## What degrades, and to what

Everything below the line is optional. This is what makes a live demo survivable.

| If this fails | Falls back to |
|---|---|
| Generated try-on | Local composite (already on screen) |
| ΔE verification | Local composite kept, no swap |
| Gemini explanations | Static per-strategy text |
| Segmentation | Background removal only; color extraction continues |
| Head generation | Photo head on the wireframe |
| Skin-tone sampling | Face-region tone |
| Strategy rungs 3–5 | Rungs 1–2 (neutral anchor, everyday neutral) |
| Live scan | Pre-scanned backup avatar, one action away |

---

## Documents

| File | Purpose | Writer |
|---|---|---|
| `contract/` | Frozen API models | PM (amendments only before freeze) |
| `contract/DECISIONS.md` | Every resolved value and behavior, per lane | PM |
| `contract/colors.json` | Lab centers, everyday-neutral flags, retail aliases | PM |
| `contract/OPEN_QUESTIONS.md` | Lane questions awaiting a PM answer | Lanes append |
| `coordination/BACKEND_API.md` | The API the frontend builds against | **PM only** |
| `coordination/FRONTEND_REQUESTS.md` | Frontend blockers, mismatches, requests | **Frontend only** |
| `PM_TASKS.md` | Phases, cut list, minimum demo, demo readiness | PM |
| `.claude/agents/*.md` | Subagent definitions | PM |
| `backend/<lane>/CLAUDE.md` | Lane domain context, auto-loaded | PM |

**One writer per coordination file.** Two writers across two laptops produces merge conflicts
in exactly the documents meant to prevent them.

---

## The minimum demo

Everything else is upside. Protect this:

> A few garments are already ingested. The user opens the app, swipes tops and bottoms, taps
> generate outfit, and sees a recommended combination rendered on their avatar. One garment is
> ingested live to prove the pipeline works.
