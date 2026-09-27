# Sponsor track submissions

Draft text for three sponsor tracks. Team: [TEAM]. Repo: [LINK]. Deployed app: [LINK]. Fill in
placeholders before submitting; nothing else in this file should be treated as final copy
without a read-through against whatever each track's submission form actually asks for.

---

## MongoDB Atlas

### Summary

Atelier stores its entire closet — garment items, avatars, and rendered outfit combinations — as
documents in MongoDB Atlas, with every image (garment cutouts, avatar scans, generated try-ons)
held in GridFS rather than on local disk. That single decision is what lets the app be
stateless: any machine, and any fresh deploy, serves the exact same closet with no manual asset
sync. A render's cache key is itself a document keyed by the outfit combination, so a repeat
combination returns instantly with zero recomputation and zero added API cost.

### How we used it

- **Document model for items.** Each garment is a document carrying its measured Lab color
  (primary and, when distinct enough, secondary), a derived color name, a neutral flag, the
  retailer's original color string and item name, and an open `attributes` object reserved for
  future enrichment — schema-flexible by design, since not every item carries the same fields.
- **Document model for avatars.** A scan produces an avatar document: a real-body cutout image,
  a line-art wireframe (used as the render loading state and as a fallback), and the landmarks
  used for garment placement.
- **Document model for renders, doubling as a cache.** A render is keyed by
  `(avatar_id, top_id, bottom_id, jacket_id)` and stored with its status (`pending` / `done` /
  `failed`), its instant local composite URL, and its Gemini-generated URL once verified. Because
  the cache lives in Mongo rather than in process memory, it survives container restarts and
  redeploys — a combination generated once is never paid for or waited on twice.
- **GridFS for all media.** Every image the app serves — garment cutouts, avatar photos and
  wireframes, generated try-ons — lives in GridFS instead of the filesystem. Local disk is used
  only as a cache in front of it. This means a fresh deploy, or a teammate's laptop, serves an
  identical closet with no separate asset-syncing step.

### What was hard

Deciding what belonged in Mongo versus what belonged in the deterministic, in-memory scoring
layer. The styling/recommendation code is intentionally pure — no database access inside a
scoring function — so the boundary is: Mongo holds facts (measured colors, saved items, cached
renders), and the scorer reads a snapshot of those facts and does no I/O of its own. Keeping
that line clean took more discipline than the schema itself. The other real difficulty was
making the render cache correct under concurrent access from multiple demo devices without
becoming its own source of latency — a cache miss should never be more expensive than the
generation it's caching.

**Team:** [TEAM] · **Links:** repo [LINK], deployed app [LINK]

---

## DigitalOcean App Platform

### Summary

The FastAPI backend runs on DigitalOcean App Platform as a single Dockerized web service,
built directly from a Dockerfile at the repo root rather than a buildpack, because the vision
pipeline depends on system libraries (MediaPipe, OpenCV) that a Python buildpack doesn't
provision. Health checks, encrypted environment-variable secrets, and autodeploy on every push
to `main` turned "did the last change break production" into a question answered in the time it
takes the health endpoint to respond, not a manual redeploy-and-poke cycle.

### How we used it

- **Dockerized FastAPI.** A single `backend/Dockerfile`, built from the repo root so the image
  can see both `backend/` and the shared `contract/` package it imports. One instance, since
  render jobs and in-process caches would otherwise be split across instances and lose track of
  in-flight generations.
- **Health checks.** `GET /api/health` is wired as the platform health check and is also kept
  open in a browser tab during live demos — it turns "is the backend actually down" into an
  instant visual check instead of a guess during a live run.
- **Env-var secrets.** `MONGODB_URI` and `GEMINI_API_KEY` are set as encrypted environment
  variables in the App Platform component, never baked into the image or committed; a
  `.dockerignore` excludes every `.env` file from the build context as a second line of defense.
- **Autodeploy from `main`.** Every push to `main` redeploys automatically, which kept the
  deployed environment honest during a hackathon timeline where "works on my laptop" is a
  constant risk.

### What was hard

The app was first created against the Python buildpack, which happily built but silently
couldn't see the `contract/` package one directory up from `backend/` and lacked the system
libraries MediaPipe needs — it failed at runtime, not at build time, which made the root cause
non-obvious. Switching the component's source directory to the repo root and its build strategy
to the Dockerfile fixed it, but diagnosing "why does this work locally and not on the platform"
under time pressure was the most expensive hour of the deploy. The other real constraint was
memory: MediaPipe and OpenCV are not lightweight, and the instance size had to be raised past
the platform default before segmentation would run reliably.

**Team:** [TEAM] · **Links:** repo [LINK], deployed app [LINK]

---

## Google Gemini

### Summary

Gemini does two distinct jobs in Atelier, each wrapped so that its failure is invisible to the
user. First, it generates a photorealistic try-on image of an outfit on the user's own avatar,
which is verified against the garment's independently measured Lab color before it's ever shown
— a generated image that comes back the wrong color never replaces the already-correct local
composite. Second, it writes a one-line, human-readable explanation for why an outfit's colors
work, under a hard 2.5-second budget with a deterministic fallback, because the app's actual
outfit ranking is never allowed to depend on an LLM call succeeding.

### How we used it

- **Image try-on, verified.** One Gemini call takes the person's photo plus the outfit's
  garments and returns a full rendered look, run in the background after an instant local
  composite is already on screen. The result is sampled and compared via ΔE2000 against each
  garment's measured Lab color from the vision pipeline; a mismatch keeps the local composite
  and the swap simply never happens.
- **Pinned models.** Both the image model and the text model are pinned to explicit version
  strings in config, never `latest`, so a model upgrade can't silently change output — or a
  demo's behavior — mid-event.
- **Background generation, not on the request path.** Nothing waits on Gemini synchronously. The
  render endpoint returns the local composite immediately; generation runs after, and the
  frontend polls for the swap. A slow or failed call costs nothing but a missed enhancement.
- **Quota discipline and caching.** Every render is cached by its exact garment combination, so
  a repeat outfit is never regenerated or re-billed. Failures back off rather than retry hard,
  and quota exhaustion degrades to the local composite rather than surfacing an error.
- **Text explanations under a strict time budget.** Outfit explanations are requested only after
  ranking is already complete and correct; a 2.5-second budget and a static per-strategy fallback
  mean an explanation is always present, Gemini or not.

### What was hard

Garment fidelity in the generated image — texture, print, and logo detail drift more than
overall color or fit — which is exactly why the ΔE2000 color check exists as a real gate rather
than a formality: it catches the most common and most visible failure mode (a garment coming
back a noticeably different color) without needing to solve full visual fidelity. The other hard
part was writing a generation prompt that reliably preserves the person's face and body identity
rather than drifting toward a generic figure, which took a small versioned eval set of
before/after pairs re-run on every prompt change rather than being tuned by eye once.

**Team:** [TEAM] · **Links:** repo [LINK], deployed app [LINK]
