# Deploying Atelier

Backend on DigitalOcean App Platform (built from `backend/Dockerfile`), frontend on Vercel,
data in MongoDB Atlas. Do the steps in order; each ends with a check.

## 0. Before you start

- [ ] **Rotate the MongoDB password** (Atlas → Database Access → edit the user). Old passwords are
      in the public git history. Put the new connection string in `backend/.env` on both
      laptops.
- [ ] **Gemini billing** is enabled for the API key (Google AI Studio). Image generation needs it.
- [ ] **Atlas network access** allows the backend host. For the hackathon, allow `0.0.0.0/0`
      (Atlas → Network Access); tighten it afterwards.
- [ ] Locally, all three pass:
      ```
      .venv/Scripts/python.exe -m pytest -q
      .venv/Scripts/python.exe -m contract.check_contract
      .venv/Scripts/python.exe tools/check_docs.py
      ```

## 1. Backend on DigitalOcean App Platform

Create App → GitHub → this repo, branch `main`, then edit the component:

| Setting | Value |
|---|---|
| Resource type | Web Service |
| Build | **Dockerfile**, path `backend/Dockerfile` |
| Source directory | `/` (repo root; the Dockerfile copies `contract/` and `backend/`) |
| HTTP port | `8000` |
| Health check | HTTP, path `/api/health` |
| Instance size | **2 GB RAM** or more (MediaPipe, OpenCV and image work) |
| Instance count | **1** (render jobs and caches live in memory; more instances lose track of renders) |
| Autodeploy | on push to `main` |

Environment variables (mark both as **Encrypted**):

| Key | Value |
|---|---|
| `MONGODB_URI` | the new Atlas connection string |
| `GEMINI_API_KEY` | the Gemini API key |

Optional: `MONGODB_DB` (default `atelier`), `GEMINI_TEXT_MODEL`, `GEMINI_IMAGE_MODEL`
(defaults pinned in `backend/config.py`).

Secrets never go in the image: `.dockerignore` excludes every `.env` file and all personal
photos.

**Check:** open `https://<your-app>.ondigitalocean.app/api/health` →
`{"status":"ok","db":"ok"}`. If `db` is `down`, check `MONGODB_URI` and Atlas network access.

## 2. Frontend on Vercel

- [ ] Import the repo, root directory `frontend`.
- [ ] Environment variable `BACKEND_URL` = `https://<your-app>.ondigitalocean.app`
      (no trailing slash, no `/api`; `next.config.ts` adds the path).
- [ ] Redeploy after setting it.

**Check:** `https://<your-vercel-app>/api/health` returns the same JSON, proving the rewrite
reaches the backend.

## 3. Smoke test on the deployed URL

- [ ] `GET /api/items` lists the demo closet (19 items after seeding).
- [ ] An item's `cutout_url` opens as an image (served from MongoDB, not local disk).
- [ ] `POST /api/outfits/generate` with `{}` returns outfits.
- [ ] Scan an avatar, render an outfit: the local composite appears at once, the generated
      image within ~15 s.

The first request after a deploy is slow (MediaPipe loads its models). Run one full cycle a
minute before presenting.

## Demo closet and media

The closet lives in MongoDB, and every image is stored in GridFS, so a fresh deploy serves the
same closet with no extra steps. To load or refresh the sample closet from a laptop:

```
.venv/Scripts/python.exe backend/vision/scripts/seed_closet.py
.venv/Scripts/python.exe tools/sync_media.py
```
