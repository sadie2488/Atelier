# Vision lane — domain notes

Why the lane works the way it does. Rules and scope are in `.claude/agents/vision.md`;
every resolved value is in the Vision section of `contract/DECISIONS.md`.

## The job
A retail product photo of a garment **worn by a model** goes in. Out comes a saved item: a
clean transparent cutout on the P0.7 canvas (`contract/ARTIFACT_SPEC.md`) plus numeric Lab
color. Two steps, always: `POST /api/items/analyze` persists nothing and returns exactly three
candidates; `POST /api/items/save` persists the chosen one; `POST /api/items/reject` persists
nothing and logs.

## Pipeline, in ship order
- **V1 intake** — JPEG/PNG/WebP up to 12 MB; EXIF-correct; PNG alpha is discarded onto white.
- **V2 isolation** — one MediaPipe person-segmentation + pose pass per image; the three
  candidates (tight / balanced / generous) differ only in post-processing. Skin comes from
  MediaPipe categories, never color thresholds. Pose region is chosen by `garment_type`
  (a dress is shoulder-to-ankle with no waist seam).
- **V3 normalization** — place the cutout on the artifact canvas using landmark-normalized
  anchors. Halt if `contract/ARTIFACT_SPEC.md` is missing.
- **V4 color** — k-means k=5 in CIELAB over alpha > 0; primary = largest cluster; one optional
  secondary (≥20% mass and ≥ΔE2000 20). Names and families from `contract/colors.json`;
  `is_neutral` from chroma only.
- **V5 endpoints** — routes in `backend/routes/items.py`; items stored via
  `backend.db.get_db()["items"]`; slug allocated at save.
- **V6 robustness** — every failure returns a contract error body; failures are appended to
  `media/_failures/rejections.jsonl` (append-only).
- **V7 enrichment** — severable; post-save only.

## Useful starting points
- `backend/vision/_reference/flatlay_pipeline/` — an earlier flat-lay pipeline (EXIF
  preprocess, rembg cutout with hole filling, k-means Lab colors with CIEDE2000 merging).
  Reuse what fits, delete the rest. It is not imported anywhere.
- Fixtures: `fixtures/images/` (retail photos on models; the true hex is the last `#rrggbb`
  in each filename), `fixtures/flatten/` (flat-lay photos), `fixtures/MANIFEST.csv`.
- MediaPipe needs Python 3.12 — use `.venv/Scripts/python.exe`. Model files download on first
  use; cache them under `backend/vision/models/`.
- Paths and settings: `backend/config.py` (`MEDIA_DIR`, `TEMP_DIR`, `FAILURE_LOG`).
