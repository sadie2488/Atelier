# Contract notes — review before freezing (about 10 minutes)

Contract version **1.0.0**, drafted from PRD Sections 2, 6, 7 and TASKS.md. `python3 -m contract.check_contract` passes.

## How to freeze

1. Read the five "Confirm" items below; change anything you disagree with (edit `schemas.py`, `enums.py`, or the `GARMENTS` table in `tools/make_fixtures.py`).
2. `python3 -m contract.tools.make_fixtures && python3 -m contract.check_contract` → must print `CONTRACT OK`.
3. `touch contract/FROZEN`, commit, push. Tell your teammate: S1 and S2 in `TASKS.md` can start.

After the freeze, changes go through the lane A human, both humans agree, bump `CONTRACT_VERSION`, push immediately.

## What's here

| File | What it is | Who uses it |
| --- | --- | --- |
| `enums.py` | Categories, patterns, statuses, error codes, and every shared threshold | All backend tasks, scorer |
| `schemas.py` | Pydantic v2 models for stored entities and every endpoint's request/response; `ENDPOINTS` registry | S1 scaffold, every backend task |
| `schema.json` | JSON Schema export of the same models | S2 generates the frontend's TypeScript types from it |
| `template_body.json` | Placeholder body: 600×1200 canvas, head slot, anchor slots, shoes area, layer order | B4 compositor; replace numbers when the drawing lands |
| `fixtures/*.json` | 19 garments (14 owned, 5 catalog), 1 avatar, 3 outfits, 1 render | Tests, S2 fixture mode |
| `fixtures/api/*.json` | Example request and response for all 11 endpoints, plus error examples | S1 scaffold serves these verbatim |
| `tools/make_fixtures.py` | Regenerates all fixtures; colors computed from hex | Humans |
| `check_contract.py` | Validates everything; tested against 10 deliberately broken cases | Humans, before freezing and after any change |

## Confirm these five (they shape the most code)

1. **"Neutral" is strict.** `is_neutral` means dominant chroma < 12: black, white, grey, cream. Navy (18), beige (18), brown (23), denim (30), and olive (30) are *not* flagged neutral. That's deliberate: the pipeline reports a measurable fact, and `SCORER.md` treats navy, denim, beige, brown, camel, and olive as "everyday neutrals" in the scoring rules. If you'd rather the flag include them, raise `NEUTRAL_CHROMA_MAX` to about 20 (catches navy and beige, not denim or brown).
2. **Ingest is always two steps**, for scans and flat-lays alike: `POST /ingest` returns candidates, `POST /ingest/{photo_id}/select` saves the tapped ones. A flat-lay returns exactly one candidate, so it's one tap. The seed loader (A3) calls the pipeline directly, not the API.
3. **Classification is synchronous** inside select, so a garment comes back `ready` or `needs_review` (or `failed`). There's no `processing` status; the PRD's data model listed one, but nothing is asynchronous.
4. **Outfit shape:** top + bottom + shoes, or dress + shoes, plus at most one outerwear. Accessories exist as a category but never appear in outfits in v1. Outfits have 2–4 items.
5. **Images are relative URLs** like `/media/cutouts/<id>.png`, served by the backend. **Lane B human:** the Next.js rewrite must proxy `/media/*` as well as `/api/*`.

## Other judgment calls (fine to accept as-is)

- **IDs** are 24-character lowercase hex strings (MongoDB ObjectIds as text). Fixture IDs encode the type in the first digit: 1 garment, 2 avatar, 3 outfit, 4 render, 5 photo.
- **User:** every record has `user_id: "demo"` (auth is mocked).
- **Colors:** 1–4 per garment (the PRD said 2–4; a plain tee has one), sorted by weight, weights sum to at most 1.
- **Formality 1–5:** 1 loungewear, 2 casual, 3 smart casual, 4 dressy, 5 formal.
- **`needs_purchase`** on each outfit lists its catalog items, so the UI can say "you'd need to buy this" without looking anything up.
- **Reasons** are at most 140 characters. `reason_source` is `llm` or `template`; `model` is set exactly when it's `llm`.
- **Next outfit** is `offset` + `limit` on `/recommend` (limit at most 5). **Swap** returns a new outfit with a new id.
- **Render** returns an image URL; the same PNG is the Save look download.
- **Avatar generation is synchronous** (may take 10–20 s). The frontend should fire `/avatar` and move straight to the waist-up capture without waiting, which is how the PRD hides the latency.
- **Guest items** are marked with the `is_guest` form field on `/avatar` and `/ingest`; catalog items are never guests.
- **Errors** always look like `{"error": {"code": "...", "message": "..."}}` with codes from `ErrorCode`.
- **Database-only fields** (raw Gemini output, the photos collection, cache keys) aren't in the contract. Modules may store extra fields as long as API output validates.
- **Unknown fields are rejected** (`extra="forbid"`), so typos fail loudly instead of disappearing.
- **Template layer order:** bottom → dress → top → outerwear → arms overlay. `arms_overlay` is null for the placeholder.

## Where this differs from the PRD doc

PRD Section 7 lists a `photos` collection, a `processing` status, `cutout_path`, and `llm_reason`. The contract drops the first two (see above) and renames the last two to `cutout_url` and `reason`. `CONTRACT_NOTES.md` wins; the PRD doc can be synced later.

## How code uses it

- **Backend:** `from contract.schemas import Garment, RecommendResponse, ...`. The repo root must be on the Python path: S1's `backend/pytest.ini` sets `pythonpath = ..`, and the Dockerfile copies `contract/` next to `backend/`.
- **Frontend:** S2 generates TypeScript types from `contract/schema.json` and serves `contract/fixtures/api/*.response.json` in fixture mode.
