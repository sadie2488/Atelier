# Issue log

**Written by the PM.** Every reported issue, who owns it, the conclusion, and its status.
Read this after every pull. Frontend requests stay in `FRONTEND_REQUESTS.md`; this log tracks
everything, including those, once the PM has responded.

**Status:** **Successful** (fixed and verified) · **Not successful** (tried; did not work or
won't be fixed, with the reason) · **In progress** (being worked on now)

Newest first. Commit hashes refer to `main` unless noted.

| # | Reported | Issue | Owner | Status | Conclusion |
|---|---|---|---|---|---|
| 18 | 2026-09-27 | Frontend redesign (look only, no functional change) | Frontend laptop | **In progress** | Rules in BACKEND_API.md "Frontend redesign: rules". Branch `frontend/redesign`; PM reviews and merges; freeze before rehearsal. |
| 17 | 2026-09-27 | Palette insights feature (+ button above "generate outfit") | PM → styling + frontend | **In progress** | Contract 2.2.0 `GET /api/insights/palette` committed locally (b6b981f). Backend (MongoDB aggregation) and a minimal page are being built on separate branches; merged to `main` together once both pass the gate. |
| 16 | 2026-09-27 | Closet garment images don't look transparent | Frontend laptop (display) | **In progress** | The PNGs ARE transparent (all 19 checked: RGBA, transparent corners, served that way live). Cause is display: `object-fit: cover` crops/zooms garments into boxes, and the add-item picker/detail popup draw a background box. Handed to the redesign (see rules). If leftover photo bits inside a cutout are meant, that is #15. |
| 15 | 2026-09-27 | Bottoms not isolated from the model (all but one wrong) | Vision | **In progress** | Isolation rework for pants/shorts/skirts (hips-down region, exclude skin/shoes/top) and an in-place re-cut of all 19 items (same ids; keep the old cutout where the new one is worse). |
| 14 | 2026-09-27 | Green named "charcoal" | PM → vision → frontend | **In progress** | Contract 2.1.0 adds `display_name` from the xkcd color survey (949 names, CC0) — e.g. `#1d4938` → "evergreen". Frontend shows it (07b343a, live). Vision is filling it for every item during #15's re-cut. |
| 13 | 2026-09-27 | Remove the "retailer says" section | Frontend | **Successful** | Removed from the closet detail panel (07b343a). |
| 12 | 2026-09-27 | Scan usually rejects; standing area small and unclear; no reasons | Avatar + frontend | **In progress** | Frontend: large full-body outline, always-visible tips, one bullet per rejection reason (07b343a, live). Backend: all failing checks reported with measurements, new too-close/too-far/facing checks, visibility 0.5 → 0.3 (ba060d7, deployed with 9ad2890). **Needs a real-camera test** on the deployed site (laptop and phone). |
| 11 | 2026-09-27 | Tests only passed with a real Gemini key in `backend/.env` | PM + avatar | **Successful** | Shared fixture blanks real secrets; avatar tests set a dummy key (9ad2890). Gate now runs in a clean checkout with no `.env`. |
| 10 | 2026-09-27 | One try-on showed black sweatpants instead of dark jeans (Sadie, top_8cfe59 + bottom_e7883c) | Avatar | **Not successful** (mitigated) | The color check can't tell dark-indigo jeans from black sweatpants (ΔE ≈ 15 < 20); garment-type swaps are out of reach for a color check. Bad cached image deleted; regenerating now fails verification, so the outfit shows the local composite. Avoid that combination on Sadie's avatar in the demo. |
| 9 | 2026-09-27 | DigitalOcean kept running the old hello-world code / failing health checks | Human + PM | **Successful** | App was still on the Python buildpack. Switched via App Spec to `backend/Dockerfile`, `source_dir: /`, port 8000, health check `/api/live` (added in 4cb29f5). Live `/api/health` = ok. |
| 8 | 2026-09-26 | Fair Isle cardigan cutout shredded; try-on fell back | Vision | **Successful** | Pattern colors inside a garment are kept (77c638d); cardigan re-cut in place; try-ons for both avatars pass and are cached. |
| 7 | 2026-09-26 | Every Gemini try-on failed | Avatar | **Successful** | Deadline was 8 s; Gemini requires ≥ 10 s (6323f3a, now 60 s). Verification rewritten to sample the generated image's own pose and skip covered garments (6f8cca3). |
| 6 | 2026-09-26 | Real scans rejected at 25° arm angle | Avatar | **Successful** | Human decision: 12° (d5ac235). Both real photos pass. |
| 5 | 2026-09-26 | Avatar should be the real body, not a drawn mannequin | Avatar | **Successful** | Real-body cutout on a 1:2 canvas (ab79d3c, DECISIONS A-B3); line art stays as loading state/fallback. |
| 4 | 2026-09-26 | Renders fired on every swipe (cost, A-R1) | Frontend | **Successful** | Render only via "see it on me" and after "generate outfit" (393a0bb). |
| 3 | 2026-09-26 | A test's cleanup deleted the real demo-closet bottoms | PM + vision | **Successful** | Restored from MongoDB; every test now gets an isolated media dir (d73fe26, 6cd8e42). |
| 2 | 2026-09-26 | Images only on one laptop's disk | PM | **Successful** | All media stored in MongoDB GridFS, served local-first (55ab4d8 and follow-ups). |
| 1 | 2026-09-26 | Old MongoDB password in public git history | Human | **Successful** | Password rotated; old one confirmed rejected; new URI in both `.env` files and DigitalOcean. |

## Known limitations (accepted; not being fixed before the demo)

- Striped garments report the larger base color as primary (green polo reads as cream).
- Light-wash denim can be named gray.
- One tight waist-down jean photo gets a poor pose read.
- Try-on takes ~12 s per new combination; repeats are cached.
