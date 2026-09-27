# Atelier

**Your closet, styled by color theory.** Snap a retail photo of a garment and Atelier cuts it
off the model, measures its true color, and files it in your digital closet. Tap **generate
outfit** for a color-harmony recommendation, and see the look on an avatar built from a scan
of you.

> Hackathon project, in active development. The backend is feature-complete for the demo; the
> frontend is being connected now.

---

## How it works

```
retail photo ──► vision ──► closet ──► styling ──► outfit ──► avatar ──► rendered look
```

1. **Ingest (vision).** MediaPipe finds the model's pose and segments their clothing. The
   garment region is chosen from body landmarks by garment type (a dress runs shoulder to
   ankle), and three candidate cutouts (tight, balanced, generous) are offered. The user picks
   one; only then is anything saved.
2. **Measure color.** K-means clustering in CIELAB over the cutout's pixels gives a primary and,
   when it's distinct enough, a secondary color. Colors stay numeric (Lab); names and families
   come from a lookup table, and "neutral" is computed from chroma.
3. **Recommend (styling).** Named color-theory strategies generate outfits: *neutral anchor*,
   *everyday-neutral base*, *analogous*, and *complementary*. A pure, deterministic scorer
   ranks them, and up to five come back with a one-line explanation.
4. **Render (avatar).** A front-facing scan becomes a line-art avatar drawn from pose
   landmarks, with the user's face at the head. Selecting an outfit returns an instant local
   composite; a Gemini-generated try-on is produced in the background, checked against the
   garments' measured colors, and swapped in when it passes.

Every step degrades gracefully: if generation is slow, fails, or runs out of quota, the local
composite stays on screen and nothing breaks.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js (App Router), TypeScript, Tailwind CSS |
| Backend | Python 3.12, FastAPI |
| Computer vision | MediaPipe (pose landmarks, multiclass segmentation, face detection), OpenCV, scikit-image, scikit-learn |
| Generative AI | Google Gemini: image generation for try-on, text for outfit explanations |
| Data | MongoDB Atlas (items, avatars, renders; media files in GridFS) |
| Hosting | Vercel (frontend), DigitalOcean App Platform (backend, Docker) |

---

## Repository layout

```
backend/
  main.py            FastAPI app: routers under /api, media under /media
  config.py, db.py   settings (from backend/.env) and MongoDB access
  media_store.py     durable media in MongoDB GridFS, local disk as a cache
  routes/            items.py · outfits.py · avatar.py
  vision/            ingest pipeline: segmentation, cutouts, color, quality checks
  styling/           scorer, strategies, selection, explanations
  avatar/            pose validation, rig, avatar drawing, compositing, Gemini try-on
  tests/             offline test suite
contract/            the API contract: Pydantic models, enums, JSON Schema, example fixtures
coordination/        BACKEND_API.md: the frontend's guide to every endpoint
frontend/            Next.js app
fixtures/            sample garment photos used for testing and the demo closet
tools/               checks and maintenance scripts
```

---

## Running locally

### Prerequisites

- Python **3.12** (MediaPipe has no 3.14 build) and Node.js 20+
- A MongoDB Atlas connection string
- A Gemini API key from Google AI Studio (image generation needs billing enabled)

### Backend

```bash
# from the repo root
python3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt   # macOS/Linux: .venv/bin/python

cp backend/.env.example backend/.env    # then fill in MONGODB_URI and GEMINI_API_KEY

.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000
```

Check `http://localhost:8000/api/health` → `{"status":"ok","db":"ok"}`. MediaPipe model files
download automatically on first use.

**Demo closet (optional):** load the sample garments in `fixtures/images/` into your database.
Safe to re-run.

```bash
.venv/Scripts/python.exe backend/vision/scripts/seed_closet.py
.venv/Scripts/python.exe tools/sync_media.py      # upload any local-only images to MongoDB
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

`next.config.ts` proxies `/api/*` and `/media/*` to `BACKEND_URL` (default
`http://localhost:8000`), so the frontend always uses relative URLs.

> **TODO (frontend):** screens, environment variables, and type generation, once the frontend
> commit lands.

---

## API at a glance

All routes live under `/api`; errors always come back as
`{"error": {"code": "...", "message": "..."}}`. Full behavior, including the render polling
cadence, is in [`coordination/BACKEND_API.md`](coordination/BACKEND_API.md). Types:
[`contract/schema.json`](contract/schema.json). Example request/response for every endpoint:
[`contract/fixtures/api/`](contract/fixtures/api/).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Backend and database status |
| POST | `/api/items/analyze` | Upload a garment photo (multipart) → 3 candidate cutouts; saves nothing |
| POST | `/api/items/save` | Keep one candidate → saved item |
| POST | `/api/items/reject` | Discard all three candidates |
| GET | `/api/items` | The closet, newest first (optional `?category=tops\|bottoms\|jackets`) |
| GET | `/api/items/{slug}` | One item, including its measured colors |
| POST | `/api/outfits/generate` | Up to 5 ranked outfits with strategy and explanation |
| POST | `/api/avatar/scan` | Full-body photo (multipart) → avatar, or a specific pose correction |
| GET | `/api/avatar/{avatar_id}` | One avatar |
| POST | `/api/render` | Outfit on avatar → instant local composite (`status` `pending` while try-on generates) |
| GET | `/api/render/{render_id}` | Poll until `done` (with `generated_url`) or `failed` (keep the local image) |

---

## Testing

```bash
.venv/Scripts/python.exe -m pytest -q                  # backend suite, fully offline
.venv/Scripts/python.exe -m contract.check_contract    # contract models and fixtures agree
.venv/Scripts/python.exe tools/check_docs.py           # project docs don't contradict each other
```

Tests never touch the network: the database, media storage, and Gemini are replaced with
in-memory stand-ins.

---

## Known limitations

- **Garments must be worn by a model.** Ingest locates the garment from the model's pose, so a
  photo needs the upper body in frame; tight waist-down crops and flat-lays are rejected with a
  clear message.
- **Striped and two-tone garments** report their larger base color as primary (a green-striped
  cream sweater reads as cream), with the accent as the secondary color.
- **Light-wash denim** sits on the boundary between blue and gray and may be named gray.
- **Generated try-on** takes about 10 seconds and costs API quota; each outfit combination is
  generated once and cached.

---

## Privacy

The avatar scan and try-on send the user's photo to Google's Gemini API. The app says so before
capture. Face photos and garment images are stored in the project's MongoDB database.

---

## Team

> **TODO:** names and roles.
