# Contract notes — v2.0.0

Contract version **2.0.0** (2026-09-26) replaces the v1 `/ingest`, `/garments`, `/recommend`
API with the Plan 2 API in `coordination/BACKEND_API.md`, plus amendments A1–A4 and the
color rules V-C1..V-C5 in `DECISIONS.md`. `python -m contract.check_contract` prints
`CONTRACT OK`.

## Regenerate and check

```
python -m contract.tools.make_fixtures   # rewrites fixtures/ and schema.json (deterministic)
python -m contract.check_contract        # must print CONTRACT OK before FROZEN exists
```

After the freeze, changes go through the PM, both humans agree, bump `CONTRACT_VERSION`,
push immediately.

## Endpoints (all under `/api`; media under top-level `/media`)

| Method | Path | Request | Response | Fixture name |
| --- | --- | --- | --- | --- |
| GET | `/health` | — | `HealthResponse` | `get_health` |
| POST | `/items/analyze` | multipart: `image` + `AnalyzeForm` fields | `AnalyzeResponse` | `post_items_analyze` |
| POST | `/items/save` | `SaveRequest` | `Item` (`SaveResponse`) | `post_items_save` |
| POST | `/items/reject` | `RejectRequest` | `RejectResponse` | `post_items_reject` |
| GET | `/items?category=` | — | `ItemListResponse` | `get_items` |
| GET | `/items/{slug}` | — | `Item` | `get_items_detail` |
| PATCH | `/items/{slug}` | `RenameRequest` `{"name"}` (1–80 chars) | `Item` | `patch_items_detail` |
| POST | `/outfits/generate` | `OutfitsGenerateRequest` (`{}` is valid) | `OutfitsGenerateResponse` | `post_outfits_generate` |
| POST | `/avatar/scan` | multipart: `image` | `AvatarScanResponse` | `post_avatar_scan` |
| GET | `/avatar/{avatar_id}` | — | `Avatar` | `get_avatar_detail` |
| POST | `/render` | `RenderRequest` | `RenderJob` | `post_render` |
| GET | `/render/{render_id}` | — | `RenderJob` | `get_render_detail` |

Errors: every 4xx/5xx body is `ErrorResponse` `{"error": {"code", "message"}}` with codes from
`ErrorCode`. `fixture_name()` drops path parameters and adds `_detail` when the path had one
(v1 had no GET-by-id routes, so there was no collision to resolve).

## Key rules the models enforce

- **Category/garment_type (A1).** `tops` → shirt, dress · `bottoms` → pants, skirt, shorts ·
  `jackets` → jacket, coat. Validated on `Item` and `AnalyzeForm`.
- **Item ids (V-A2).** `<prefix>_<6 hex>`; prefix by garment_type: shirt → `top`, dress →
  `dress`, pants/skirt/shorts → `bottom`, jacket/coat → `jacket`. Allocated at save.
- **Other ids.** `tmp_<12 hex>`, `avatar_<6 hex>`, `outfit_<6 hex>`,
  `render_<12 hex>` (deterministic key of avatar + top + bottom + jacket, so a repeat is a cache hit).
- **Colors (V-C1..V-C5).** `ExtractedColor` carries lab, lch, hex, name, family, is_neutral,
  everyday_neutral. `is_neutral == chroma < 12`. `name` is a `colors.json` name or `unmapped`;
  family and everyday_neutral must match the table (`unmapped` → family `unmapped`, false).
  A secondary color must be ≥ ΔE2000 20 from the primary. The nearest-center rule itself is
  checked on fixtures by `check_contract` (via `tools/color.py`, which has CIEDE2000).
- **Attributes (A3).** `Item.attributes` is an open object, `{}` by default.
- **Analyze.** Exactly three candidates, index 0–2, variants tight/balanced/generous in order.
  Retailer `color` and `item_name` form fields are optional and become `retailer_color` /
  `retailer_item_name` on the saved item.
- **Item list.** Ordered by `created_at`, newest first; unique ids.
- **Outfits.** `top_id` (a `top_` or `dress_` slug) + `bottom_id` + optional `jacket_id`;
  `sandwich` requires a jacket. Response: ≤5, best score first, score 0–1, unique
  outfit_ids and combinations, ≤2 per strategy, ≤2 sharing a top or bottom (jackets exempt).
  `explanation` is always non-empty.
- **Render (A4).** `local_url` always present; `generated_url` set exactly when
  `status == done`. `failed` keeps only the local composite.
- **Media URLs** are relative `/media/<dir>/<file>.png`; unknown fields are rejected everywhere.

## Files

| File | What it is |
| --- | --- |
| `enums.py` | Category, GarmentType, VALID_PAIRS, SLUG_PREFIX, Strategy, RenderStatus, CandidateVariant, ErrorCode, thresholds |
| `schemas.py` | Pydantic v2 models, `ENDPOINTS`, `API_MODELS`, `fixture_name()` |
| `schema.json` | JSON Schema of `API_MODELS` (frontend TypeScript source) |
| `fixtures/items.json` | 10-item closet: 4 tops (1 dress), 4 bottoms, 2 jackets; 2 strict neutrals |
| `fixtures/outfits.json`, `avatar.json`, `render.json` | 5 outfits; 1 avatar; `[pending, done]` for one render_id |
| `fixtures/api/` | Request/response example per endpoint, plus `errors.json` |
| `tools/make_fixtures.py`, `tools/color.py` | Generator; Lab/LCh/CIEDE2000 and colors.json lookup |

`template_body.json` is a v1 leftover (fixed-pixel body template). v2 places garments on pose
landmarks (A-B2), so nothing in the contract validates or uses it.
