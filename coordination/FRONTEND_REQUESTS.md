# Frontend → Backend

**Written by: the frontend agent/session only.** The backend PM reads this every dispatch
cycle and responds by editing `coordination/BACKEND_API.md` — **not** by editing this file.
Two writers on one file is how you get merge conflicts between two laptops.

**Cadence:** append an entry the moment you are blocked or notice a mismatch, then push. Do
not batch requests; a blocked frontend and a backend that does not know is the most expensive
state in this project.

---

## How to use this

Append a new row. Newest at the top. Leave `Status` and `Resolution` blank — the PM fills
those in when it responds, and points you at the `BACKEND_API.md` change.

**Types:**

- `BLOCKED` — you cannot proceed. The PM treats these first.
- `MISMATCH` — the API behaves differently than `BACKEND_API.md` says. Include what you sent,
  what you expected, what you got.
- `REQUEST` — you need a field, an endpoint, or a behavior that does not exist.
- `QUESTION` — a behavior is unspecified and you do not want to guess.
- `FYI` — a frontend decision the backend should know about.

**When you are blocked, keep building against a mock** shaped like `BACKEND_API.md` and flag
it here. Do not wait idle, and do not silently invent a different shape — an undeclared mock
that diverges from the real API is worse than being blocked, because nobody finds out until
integration.

---

## Open

| # | Type | Raised | Detail | Status | Resolution |
|---|---|---|---|---|---|
| 6 | FYI | 2026-09-26 | **Frontend port is done but only partly verified against the real backend.** The Lovable design is ported to Next.js (`/`, `/closet`, `/scan`, `/add-item`, `/stylist`); build and lint pass. Verified on the frontend laptop with the real backend and Atlas: `/api/health`, `/api/items` (19 items), `/api/outfits/generate`, `/media/*`, `POST /api/items/analyze` (multipart, ~10 s, 3 candidates) and `/api/items/reject`, all through the Next `/api` rewrite. **Not verified:** `/api/avatar/scan`, `/api/render` and its polling swap (no avatar exists in the DB yet, and the fixture id `avatar_427165` returns `not_found`), `/api/items/save`, and the UI in a real browser. The first real scan on this laptop will exercise them. | | |
| 5 | FYI | 2026-09-26 | **MongoDB access.** The Atlas user's password was changed on this laptop after the old one was pasted into a chat transcript. Anything else using that database user (the PM's backend, deployed App Platform env vars, the other laptop's `backend/.env`) needs the new `MONGODB_URI`. The frontend laptop's backend also needed `pip install -r backend/requirements.txt` (the venv had no pip and no numpy) after pulling. **PM: please confirm the deployed backend and your own `.env` have the updated URI.** | | |
| 4 | FYI | 2026-09-26 | **Renders fire on selection.** The stylist calls `POST /api/render` about 0.5 s after the tops/bottoms/jacket selection settles (including on plain swipes), because the frontend may not composite garments itself. Each new combination can start a Gemini generation; repeats hit the cache. If that cost is a problem, say so and the frontend will limit rendering to the "generate outfit" button. | | |
| 3 | FYI | 2026-09-26 | **Removed/decided in the UI:** the Lovable "color palette" button has no API behind it and was dropped. Bottoms include `pants` (BACKEND_API valid pairs), and there is no shoes category. "none of these" on the cutout picker calls `POST /api/items/reject`. `frontend/.gitignore` matches `.env*`, so `frontend/.env.example` (BACKEND_URL, NEXT_PUBLIC_BACKUP_AVATAR_ID) is ignored by git; add an exception if it should be committed. | | |
| 2 | MISMATCH | 2026-09-26 | **Color extraction looks wrong on a fixture.** Sent `fixtures/images/sharp green Whoa So Soft Fitted Sweater Polo #048c57.png` to `POST /api/items/analyze` (`category=tops`, `garment_type=shirt`). Expected a green primary color (about `#048c57`); got `primary_color.hex` `#d2cdb7`, name "cream", `is_neutral: true` for all three candidates (`#d2cdb7`, `#d3ceb8`, `#dddac7`). The cutout may include the light background, or sampling is off. The detail panel shows this swatch next to the retailer color, so a wrong swatch is visible to judges. | | |
| 1 | QUESTION | 2026-09-26 | **Backup avatar id.** The frontend has a one-action trigger: a "use backup avatar" button on `/scan`, and `/scan?backup=<avatar_id>` (or `?backup=1`) which calls `GET /api/avatar/{id}` and stores it as the current avatar. The id comes from `NEXT_PUBLIC_BACKUP_AVATAR_ID` (see `frontend/.env.example`); the button is hidden while it is unset. **Backend PM: please prompt the human to do the real pre-scan (A8), then tell us the `avatar_id` (or expose it another way, e.g. an endpoint) so it can be set in Vercel.** | | |

## Resolved

| # | Type | Detail | Resolution |
|---|---|---|---|
| — | — | *(none yet)* | — |

---

## Scope boundary

The two halves are split cleanly. Raise anything that crosses this line **here, before
building it** — do not implement across the boundary and do not assume the other side has it
covered.

**Frontend owns:** camera capture and the pose outline overlay, client-side downscaling, swipe
lists and their rendering, the generate button, positioning garments at index 0, the metadata
detail panel, polling and the image swap, all loading and degraded states, the backup-avatar
shortcut, the consent line.

**Backend owns:** every endpoint, segmentation and cutouts, color extraction, scoring and
outfit selection, avatar assembly, local compositing, generation and its verification, caching,
all media files.

**Grey areas — raise as `QUESTION`, do not decide unilaterally:**

- Which side enforces an image size or dimension limit
- Whether a value is computed server-side or derived in the client
- Anything that would mean the same logic existing on both sides

If you find yourself writing color logic, scoring logic, or garment placement logic in the
frontend, stop and raise it. That work belongs to a backend lane and duplicating it will
diverge.
