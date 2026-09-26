# Closet App PRD — 36-Hour Hackathon

Sep 26, 2026

**Version 2: two people, two agents.** Each person drives one Claude Code session through their lane's tasks. Version 1 (an architect session dispatching parallel expert agents) is archived in `archive/parallel-agents-v1/` in the repo. Working files: `CLAUDE.md`, `TASKS.md`, `WORKFLOW.md`, `contract/`, `SCORER.md`.

## 1. Problem and target user

People with disorganized wardrobes can't see what they own or which pieces work together, so they default to the same few outfits. The product scans the user into a drawn avatar, turns what they're wearing into closet items, and builds outfits on demand that are shown on the avatar.

**Target user:** anyone with a disorganized closet, large or small. The demo uses a small closet because of limited resources; nothing in the design depends on closet size.

**Demo flow:**

1. The app opens and scans the user's face; a drawn avatar with their likeness appears on a template body.
2. The user steps back for a waist-up capture; their top (or jacket) is cut out and saved as a closet item.
3. They click **Make outfits**; an outfit built around that item, from pre-saved owned and catalog pieces, appears with a one-line reason.
4. The outfit is layered onto their avatar.

**AI features to emphasize:** the face-to-avatar scan, garment segmentation, and the outfit recommendations.

**Team goals beyond winning:** technically substantive CV/ML components, resume-worthy bullets, and real learning exposure.

**Out of scope for this PRD:** visual design and art (the team provides layout drawings and the template body) and the pitch.

## 2. Scoped MVP

The MVP is the four-step demo flow: face scan → top into the closet → **Make outfits** → outfit on the avatar. Everything above the cut line must work before stretch work starts.

**The template body is what makes the avatar reliable.** Only the head is personalized. The body is one team-drawn figure in a fixed pose with fixed anchor points (neck, shoulders, waist, hips), so every garment is placed by scaling it to those slots. No body tracking is needed, and it works the same for every user.

**Framing constraint:** a face-only shot doesn't show enough of the top to cut it out. The scan therefore takes two captures: a close-up for the face, then a waist-up capture at about 1–1.5 m, which a laptop webcam can handle. If the waist-up capture fails, the user hands over the garment and it goes through the flat-lay path.

| Feature | Tag | Notes |
| --- | --- | --- |
| **Guided scan:** face outline and countdown, then a waist-up outline and countdown, with a quality check that the face (or torso) is in frame and facing forward | LIVE | A bad capture ruins everything after it, so the check blocks the next step. |
| **Face to avatar:** Gemini image generation turns the face capture into a drawn head in your art style, placed on the template body | LIVE | Fallback: the face photo cut out and placed on the drawn body. |
| **Top to closet:** clothing segmentation on the waist-up capture, then the user taps the garment to save (jacket or shirt) and can fix its category | LIVE | Only the outermost visible top is reliable; a shirt under an open jacket may be partial. |
| Flat-lay ingest from photo upload | LIVE | Loads owned seed items and catalog items; also the judge handoff fallback. |
| Color extraction in Lab, perceptual merging of near-duplicates | LIVE | 1–4 weighted colors plus a neutral flag per garment. |
| Garment classification via Gemini structured output | LIVE | Fixed enums, schema-validated; retry once, then flag for manual edit. |
| **Owned vs. catalog flag** on every item | LIVE | Outfits label catalog pieces as "you'd need to buy this." |
| **Make outfits button:** builds outfits around the scanned item | LIVE | Rule scorer plus Gemini re-rank with a one-line reason. Seed results pre-cached; new items run live. |
| **Next outfit** and **swap one piece** | LIVE | Keeps the demo going past the first recommendation. |
| **Outfit on avatar:** garments layered onto the template body in a fixed order (pants, top, jacket, arms on top); shoes shown beside the avatar | LIVE | Cutouts are scaled to the template's anchor slots. It looks like a collage, which suits the drawn style. |
| **Save look:** export the dressed avatar as an image | LIVE | Cheap takeaway for judges. |
| Consent screen before the scan; originals deleted after processing | LIVE | Only the stylized avatar head and garment cutouts are kept. |
| **Reset demo closet**, removing guest avatars and scanned items | LIVE | Every judge starts from the same state. |
| Seed closet: ~15 owned items plus a fixed sample catalog of product images downloaded before the demo | SEEDED | All loaded through the real pipeline; no live scraping. |
| App screens from the team's layout drawings | LIVE | Renders whatever is in the database. |
| Auth | MOCKED | One hardcoded demo user. |

**Cut line: everything below is stretch (Section 3).**

**Cut entirely:** personal color palette, occasion chips, any chat interface, multi-user accounts. Raspberry Pi and screen stay cut; full-body scanning hardware is a stretch goal only.

**MVP definition of done:** a judge is scanned at the table, their avatar appears, their top lands in the closet, and one click shows a full outfit on their avatar with a reason, all within about a minute, on the deployed site.

## 3. Stretch features, ranked

Live AR stays first. Shop check is gone because the owned-vs-catalog flag in the MVP covers most of it.

| Rank | Feature | Est. hours | Why this rank |
| --- | --- | --- | --- |
| 1 | **Live AR:** the recommended outfit follows the user on the live camera feed, using MediaPipe Pose | 6–10 | The strongest scanning feature and best CV learning; the highest risk. Starts only after Rung 2; hidden unless smooth at freeze. |
| 2 | **Full-body scan:** a phone or external camera at 2–3 m (or added hardware) captures the whole body, so bottoms can be scanned too and the avatar body can reflect the user | 3–6, plus acquisition time for any hardware | A phone used as a webcam is far cheaper than new hardware; try that first. |
| 3 | **Generative try-on render:** the image model renders the avatar actually wearing the outfit | 2–3 | Impressive, but it can shift garment colors. Show it only as a second view next to the collage avatar. |
| 4 | **Gap finder:** the missing item that would unlock the most new outfits | 1–2 | A pure function over scorer output; a good spare-time task. |
| 5 | Wear log | 1–2 | Invisible to judges. |

## 4. Stack

The frontend is Next.js on Vercel, and the backend is a Python FastAPI service on DigitalOcean App Platform. Next.js is a presentation layer only: all business logic, CV, image generation, and compositing live in FastAPI.

| Layer | Choice | Why | Rejected alternative |
| --- | --- | --- | --- |
| Frontend | Next.js (App Router) | Team preference; native to Vercel. Rewrites proxy `/api/*` to the backend, so the browser sees one origin and CORS disappears. They must proxy `/media/*` too. Verify upload size limits through the proxy during setup. Camera and MediaPipe code must be client components. | Vite + React: no proxy, not the team's choice. |
| Frontend hosting | Vercel | Familiar; preview URLs for every pushed branch. | DO static site: loses familiarity and previews. |
| Backend | FastAPI (Python) | The Pydantic models in the contract folder are the frozen contract. | Next.js API routes: splits logic across two languages. |
| Backend hosting | DigitalOcean App Platform, Docker, instance with at least 2 GB RAM | Automatic HTTPS; runs the PyTorch models Vercel can't; satisfies the DO track. | Vercel Python functions: bundle limits exclude the models. |
| Camera capture | Browser webcam with guided outlines and countdowns | Nothing to install. | Phone capture: kept for the full-body stretch goal. |
| Scan quality check | MediaPipe Face Detector and Pose Landmarker (web) | Confirms the face or torso is in frame and facing forward before capture; the same library powers live AR later. | Checking on the backend: slower feedback to the user. |
| Face to avatar | Gemini image generation, prompted with the face capture and a style reference drawn by the team | Stylized likeness in your art style; strengthens the Gemini track. | A face-swap model: heavier setup and a worse fit for a drawn look. |
| Avatar body | One team-drawn template body with fixed anchor points | No body tracking needed; garments are placed identically for every user. | Per-user pose detection on a generated body: unpredictable. |
| Outfit on avatar | Backend compositing with Pillow: each cutout scaled to its anchor slot and layered in a fixed order | One source of truth for display and **Save look** export. | Browser canvas compositing: duplicates logic in the frontend. |
| Garment segmentation | Pretrained clothing-segmentation SegFormer from Hugging Face | Per-pixel garment classes that exclude skin. Verify the exact model in Phase 0 on waist-up photos of both of you. | Gemini masks: less predictable. SAM: needs prompts. |
| Flat-lay background removal | rembg | Mainstream, CPU, no key. | remove.bg: credit caps. |
| Color | OpenCV + scikit-learn k-means in Lab; CIEDE2000 via scikit-image | Perceptually correct color math. | RGB k-means: perceptually wrong. |
| VLM + re-rank | Gemini (Flash tier), structured JSON output | One key covers classification and ranking. | Local open-source VLM: slow on CPU. |
| Database | MongoDB Atlas free tier | Garments are document-shaped. | Postgres or Tiger Data: relational overhead. |
| Image storage | PNGs on backend disk, paths in Mongo | Zero extra credentials. | DO Spaces or S3: another credential. |
| Design and art | Team-provided layout drawings, template body, and avatar style reference | Out of scope for this PRD. | — |
| Agents | Claude Code: one session per person | Each person drives one agent through their lane's tasks in order. See Section 9. | Several parallel agents per person: more review and coordination than two people can absorb (v1, archived). |

## 5. Sponsor tracks

Target four tracks: Gemini, Microsoft, MongoDB Atlas, and DigitalOcean. Each is satisfied by something the product needs anyway. Put zero effort into the other four.

| Rank | Track | Feature that satisfies it | Extra cost |
| --- | --- | --- | --- |
| 1 | Gemini | Three distinct uses: image generation for the avatar, structured-output garment classification, and the grounded re-rank with reasons. | ~0 |
| 2 | Microsoft | A person completes a real task with no chat window: scanning into an avatar, adding their top to a closet, and getting a dressed outfit in one click. | ~0 beyond the MVP |
| 3 | MongoDB Atlas | Documents for avatars, garments (owned and catalog), and outfits. | ~0 |
| 4 | DigitalOcean | App Platform hosts the CV and compositing backend, which Vercel can't run. | Credits depend on reaching the MLH coach |
| — | Tiger Data, Snowflake, ElevenLabs, Assurant | None. | Zero effort |

**Honesty flag:** at demo scale, a JSON file would work as well as MongoDB. It stays because it doesn't change the UX and a real closet would outgrow a file.

**Assurant, reconsidered:** the product now keeps a likeness of the user. The consent screen and deletion of original captures are a small but honest fit. Still zero-effort; enter only if it costs nothing extra.

### Resolving the Microsoft chatbot tension

The LLM never faces the user. Every AI feature is triggered by a camera capture or a button. The re-rank receives structured candidate outfits and returns JSON (an ordering plus a short reason each), validated so it can only reference candidate IDs. There is no free-text input anywhere. If Gemini is down, recommendations fall back to scorer order and the avatar falls back to the photo cutout head.

## 6. Architecture

Four backend calls carry the demo: `POST /avatar` (face capture → avatar), `POST /ingest` (waist-up capture or photo → garments), `POST /recommend` (on **Make outfits**), and `POST /render` (outfit → dressed avatar image). Each pipeline stage is a separate module, so each can be built and tested on its own.

```mermaid
flowchart LR
  F[Face capture\nquality-checked in browser] --> AV[Gemini image gen\ndrawn head]
  AV --> TB[Head placed on\ntemplate body]
  W[Waist-up capture] --> SG[Clothing segmentation]
  UP[Flat-lay upload\nowned or catalog] --> RB[Background removal]
  SG --> PK[User taps garment\nto save]
  PK --> CO[Cutout PNG\noriginals deleted]
  RB --> CO
  CO --> K[Color extraction]
  CO --> G[Gemini classify]
  K --> DB[(MongoDB Atlas)]
  G --> DB
  TB --> DB
  BTN[Make outfits] --> RS[Candidates + rule scorer]
  DB --> RS
  RS --> RR[Gemini re-rank\nreasons]
  RR --> RN[Render: cutouts scaled\nto template anchors]
  RN --> UI[Dressed avatar\n+ reason + Save look]
```

**Request path:** the Next.js app proxies `/api/*` and `/media/*` to FastAPI. The browser never calls Gemini or MongoDB directly, and no keys reach the frontend.

**Scan flow:** the browser shows a face outline, waits for the quality check to pass, and captures. The backend generates the drawn head and stores the avatar. Then the browser shows a waist-up outline and captures again. The backend segments garments, the user taps the one to save, and both original captures are deleted.

**Recommend flow:** candidates are valid category combinations that include the scanned item, drawn from owned and catalog items. The rule scorer ranks them on hue harmony, pattern clash, and formality spread; Gemini re-orders the top candidates and writes the reasons. **Next outfit** steps down the ranked list; **swap one piece** re-scores with the other pieces fixed.

**Render flow:** each garment's cutout is scaled from its bounding box to the matching anchor slot on the template body and layered in a fixed order (pants, top, jacket, arms on top). Shoes are placed beside the avatar. The result is cached per avatar and outfit, and the same image is what **Save look** exports.

**Demo reset:** guest avatars and scanned items carry a flag; **Reset demo closet** removes them and their cached outfits and renders.

## 7. Data model and API

The contract in `contract/` is the source of truth: Pydantic models, enums and thresholds, fixtures, and example requests and responses for every endpoint. `contract/CONTRACT_NOTES.md` explains every decision; once reviewed, `contract/FROZEN` is committed and changes need both people's agreement.

| Entity | Key fields |
| --- | --- |
| Garment | `source` scan or flatlay; `ownership` owned or catalog; `status` ready, needs_review, or failed; `is_guest`; `cutout_url`; `bbox`; 1–4 `colors` (Lab, LCh, hex, weight); `is_neutral`; `category`; `pattern`; `formality` 1–5; `style_tags` |
| Avatar | `head_url`; `head_source` generated or photo_fallback; `is_guest` |
| Outfit | `anchor_id`; 2–4 `item_ids`; `needs_purchase` (its catalog items); `rank`; `rule_score` with hue, pattern, and formality breakdown; `reason` (at most 140 characters) from the LLM or a template |
| Render | `avatar_id`; `outfit_id`; `image_url` (the same PNG is the Save look download) |
| Template body | 600×1200 placeholder canvas; head slot; anchor slots for top, bottom, dress, outerwear; shoes area; layer order bottom → dress → top → outerwear → arms |

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Status and contract version |
| `POST /avatar` | Face capture → avatar (drawn head or photo fallback) |
| `POST /ingest` | Scan or flat-lay photo → garment candidates (nothing saved yet) |
| `POST /ingest/{photo_id}/select` | Save the tapped candidates; classification runs here |
| `GET /garments`, `PATCH /garments/{id}`, `DELETE /garments/{id}` | Closet list, edit sheet, delete |
| `POST /recommend` | The Make outfits button; `offset` and `limit` give Next outfit |
| `POST /recommend/swap` | Replace one piece, keep the rest |
| `POST /render` | Dressed avatar image |
| `POST /demo/reset` | Remove guest avatars and garments and everything derived from them |

**Decisions worth knowing:** ingest is always two steps (a flat-lay returns one candidate, so it's one tap); classification is synchronous, so there's no processing status; images are relative `/media/...` URLs served by the backend; IDs are 24-character hex strings; outfits are top + bottom + shoes or dress + shoes, plus at most one outerwear; `is_neutral` is strict (black, white, grey, cream) and the scorer treats navy, denim, beige, brown, camel, and olive as everyday neutrals. Scoring rules and their verified test cases are in `SCORER.md`.

## 8. Build plan: two people, two agents

Each person drives one Claude Code session through their lane's tasks in `TASKS.md`, in order. The parallelism comes from the two of you working in separate folders; each agent works on one task at a time. Phases are ordered by dependency, not the clock, and every phase ends on a demo rung so you always have something submittable. The only fixed times are **feature freeze (Sun 7 AM)**, **final video recorded (~8:30 AM)**, and **submission (Sun 10 AM)**.

| | Lane A: Scan & avatar | Lane B: Recommend & render |
| --- | --- | --- |
| Who | The person with more CV experience, plus Agent A | The other person, plus Agent B |
| Backend | Scaffold, CV pipeline, segmentation, avatar head, demo reset, `routes_a.py` | Gemini wrapper, candidates and scorer, re-rank, compositor, `routes_b.py` |
| Frontend | Scan UI (camera, quality checks, garment select) | App scaffold, closet screen, outfit screen |
| Task order | S1 → A1 → A2 → A3 → A4 → A5 → A6 → A7 | S2 → B1 → B4 → B2 → B3 → B5 → B6 |

**Cross-lane dependencies** (the only times one of you waits on the other): B1 needs S1; A2 and A5 need B1; A6 needs S2. That's why both lanes start with their scaffold, and lane B does the Gemini wrapper second.

```mermaid
flowchart LR
  P0[Phase 0\nSetup] --> P1[Phase 1\nFoundations] --> R1{{Rung 1\nseed closet +\noutfit on template}}
  R1 --> P2[Phase 2\nCore AI] --> R2{{Rung 2\nfull 4-step flow}}
  R2 --> P3[Phase 3\nJudge-ready] --> R3{{Rung 3\nstrangers scan reliably}}
  R2 --> P4[Phase 4\nStretch]
  R3 --> P5[Phase 5\nFreeze + ship]
  P4 --> P5
```

### Phase 0: Setup (both)

- [ ] Accounts, repo, venv, frontend app, and a hello-world round trip deployed (Vercel → DigitalOcean → MongoDB), following Setup in `WORKFLOW.md`.
- [ ] Contract reviewed and `contract/FROZEN` pushed.
- [ ] Segmentation model and Gemini image generation each tried once on photos of both of you.
- [ ] Template body drawing started (the placeholder body works until it's done).

### Phase 1: Foundations

- Lane A: **S1** backend scaffold, **A1** flat-lay pipeline; photograph the ~15 seed items while the agent works.
- Lane B: **S2** frontend scaffold, **B1** Gemini wrapper (unblocks A2 and A5), **B4** compositor on the placeholder body.
- **Rung 1:** the seed closet's cutouts and swatches exist, and a fixture outfit renders correctly on the template body.

### Phase 2: Core AI

- Lane A: **A2** classification, **A3** seed and catalog loader, **A4** segmentation and ingest endpoints, **A5** avatar head, **A6** scan UI.
- Lane B: **B2** candidates and scorer, **B3** re-rank with next and swap, **B5** closet screen, **B6** outfit screen with Save look and reset.
- **Rung 2:** on the deployed site, one of you is scanned, their top lands in the closet, and one click shows a full outfit on their avatar with a reason. Record a rough screen capture immediately as insurance.

### Phase 3: Judge-ready

- Lane A: **A7** demo reset; scan at least 5 strangers (glasses, hair over the face, jackets, dark and patterned tops) and fix the worst failure; confirm the flat-lay handoff works.
- Lane B: Gemini fallbacks for the avatar and the re-rank; pre-warm the cache for the seed closet; loading and error states.
- Both: production deploy verified; Devpost draft.
- **Rung 3:** a stranger gets through all four steps under venue lighting in about a minute.

### Phase 4: Stretch (after Rung 2, never at Phase 3's expense)

- Lane A: live AR. Lane B: generative try-on render as a second view. Either: full-body scan with a phone as the camera; gap finder.

### Phase 5: Freeze and ship

- [ ] **Sun 7 AM: feature freeze.** Anything not solid is hidden from the UI.
- [ ] By ~8:30 AM: final video recorded on the deployed site.
- [ ] By 10 AM: Devpost submitted with the video, repo link, and track selections.
- [ ] 10–11 AM buffer: set up the table (camera height, a floor mark at the waist-up distance, plain backdrop, lighting), reset the demo closet, charge laptops.

**Flexibility rules:** a lane that finishes early takes its next task or a spare-time task, never the other lane's files. At every rung, spend 5 minutes demoing to each other and re-scope; if you're behind, cut from the bottom of the stretch list, never the MVP. Live AR starts only after Rung 2 and is hidden unless it's smooth at freeze. Stagger sleep so one person is always awake.

## 9. Working with two agents

One Claude Code session per person, on their own laptop, working through one task at a time. Both agents read the same `CLAUDE.md`, which holds every rule they follow; `WORKFLOW.md` is the humans' routine.

**Why two agents and not more:** your review time and usage limits are the real constraints, most of the work is a dependency chain that parallel agents can't speed up, and two lanes in separate folders already give you real parallelism. A single agent per person is also the best way to actually learn the stack you're building. The parallel-agent setup (v1) is archived in `archive/parallel-agents-v1/` if you want it for stretch work later.

**The loop for every task:**

1. `git pull --rebase` on `main`, then branch: `<lane>/<task>-<name>`, e.g. `a/A1-flatlay`.
2. In Claude Code: `/task A1`. It reads only that task's section of `TASKS.md`, says what it will build, implements it, runs the task's check, and reports files changed, the check output, a commit message, and anything the other lane needs.
3. The human reviews the diff, runs the check and the app, and commits.
4. Merge into `main`, push, and tell your teammate. Every push redeploys both apps, so only merge working code.
5. `/clear` before the next task.

**What the agents follow (from `CLAUDE.md`):**

- Stay in your lane's folders; the contract, `SCORER.md`, and `next.config` are read-only.
- If you see build errors in files you didn't edit, don't fix them: wait 30 seconds and retry, at most 3 times, then tell your human.
- Commit on the feature branch; never push, merge into main, force, or hard-reset.
- No chat UI or free-text LLM input; every Gemini call goes through the wrapper; no business logic in Next.js; camera code in client components only.
- Never read or commit secrets; tests run offline on fixtures and are never edited to pass; no silent fallbacks.
- Browser automation only in the agent's own headless browser, never logged in.
- Timebox: 45 minutes or 3 failed attempts, then stop and explain.
- Token budget: read only what the task needs, keep output short, don't open images.

**Guardrails in `.claude/`:** a `/task` command, and permission deny rules for force-push, hard reset, and reading `.env` files.

**When a second agent is OK:** only for a small, independent job that can't break anything (tests for merged code, loading and error states, the Devpost draft), on its own branch, reviewed when your main task finishes.

**Resume bullets this plan produces:** camera-based scanning with quality checks, generative avatar creation, and clothing segmentation; template-anchored garment compositing; perceptual color extraction (Lab k-means, CIEDE2000) and a color-harmony scoring engine; grounded LLM re-ranking with schema-validated structured output; a typed API contract shared by a Python backend and a TypeScript frontend; AI-assisted development with Claude Code; real-time pose-tracked AR try-on (stretch).

## 10. Risk register

The top risks are now the avatar generation, garment segmentation on strangers, and the frontend-to-backend connection. Each has a fallback decided now.

| Risk | Likelihood | Impact | Pre-planned fallback |
| --- | --- | --- | --- |
| Gemini image generation gives a poor likeness, is slow, or declines to edit a real person's photo | Medium | High | Tested in Phase 0 on both of you. Fallback: the face photo cut out and placed on the drawn body, which is always available. |
| Segmentation fails on a stranger's top (dark colors, busy patterns, open jackets over shirts) | High | High | Tested on at least 5 strangers in Phase 3; tap-to-select and category edit; flat-lay handoff as the last resort. |
| Garments look wrong on the template body (proportions, sleeves, necklines) | Medium | Medium | Tune anchor slots on the seed items in Phase 1; the drawn style makes collage edges acceptable. Prefer catalog images shot flat or on a hidden mannequin. |
| Next.js rewrite proxy rejects large uploads, or CORS/HTTPS errors | Medium | Fatal | Tested in Phase 0 with a full-size capture. Fallback: call the backend directly with CORS; last resort a laptop backend behind a Cloudflare quick tunnel. |
| A merge breaks main while both of you are pushing | High | High | Separate lane folders, frozen contract, feature branches, run the check and the app before merging, pull before every task. If main breaks, revert the merge first and debug on a branch. |
| Live AR eats the night | High | High | Starts only after Rung 2; Phase 3 wins every conflict; hidden unless smooth at freeze. |
| The full four-step flow takes too long at the table | Medium | High | Avatar generation runs in the background while the waist-up capture happens; seed recommendations and renders pre-cached. Target is about a minute. |
| DO credits delayed, or App Platform runs out of memory | Medium | High | Choose an instance with enough RAM up front; bake model weights into the Docker image; laptop plus tunnel as fallback. |
| Venue lighting skews scanned colors | High | Medium | Gray-world white balance; plain backdrop and a lamp at the table; the edit sheet for colors. |
| Gemini rate limit or latency during judging | Medium | High | Pre-cached seed recommendations; scorer order with template reasons as fallback. |
| A judge doesn't want to be scanned | Low | Medium | Consent screen; originals deleted; the demo can run on one of you instead. |
| Template body or layout drawings arrive late | Medium | High | Lane B builds against a placeholder rectangle body with the same anchor JSON and swaps the drawing in when it lands. |
| Exhaustion causes bad merges late at night | High | High | Staggered sleep; nothing merges unless its check passes and the app runs. |

## 11. Devil's-advocate pass

These arguments led to five revisions (the template body, the second waist-up capture, the photo-head fallback, everyday neutrals in the scorer, and two agents instead of many) and defend the rest.

**"A face-only scan can't see the top you want to add to the closet."** Correct; a head-and-shoulders frame shows only a collar. **Revised:** the scan takes two captures, a face close-up and then a waist-up shot at 1–1.5 m, which a laptop webcam can handle.

**"Dressing a generated avatar means detecting its body pose, which will be unpredictable."** Correct. **Revised:** only the head is generated; the body is one fixed team-drawn template with measured anchor slots, so compositing is deterministic.

**"The avatar depends entirely on Gemini image generation."** It's the least controllable call in the project. **Revised:** the photo-cutout head on the drawn body is a guaranteed fallback, tested in Phase 0.

**"One template body doesn't represent every user."** A fair criticism. The template is a deliberate MVP trade-off for reliability; offering a few template bodies to choose from, or the full-body scan stretch goal, addresses it later.

**"A collage avatar looks cheap next to generative try-on."** On a photo it would. On a drawn avatar it reads as a style, and it keeps garment colors exact, which is the product. **Defended:** generative try-on is stretch 3 as a second view, never the only view.

**"Skip the Python pipeline; let Gemini read colors from the raw photo."** **Defended:** LLMs are unreliable at exact color values, and segmentation is what produces the cutouts the avatar wears.

**"Next.js adds complexity over Vite for a thin frontend."** **Defended:** the rewrite proxy removes CORS, and the CLAUDE.md rules keep Next.js a presentation layer.

**"Navy, beige, brown, and denim are neutrals; the scorer will treat them as clashing colors."** Correct: measured, they have far more color than the strict neutral cutoff allows. **Revised:** the pipeline's `is_neutral` stays strict and measurable, and `SCORER.md` treats navy, denim, beige, brown, camel, and olive as everyday neutrals that go with anything.

**"Parallel agents would build it faster."** Only if review and usage limits weren't the bottleneck, and they are. Most tasks form a chain, and two people in separate folders already work in parallel. **Revised:** one agent per person, each working through its lane in order. The parallel setup is archived and can come back for stretch work.

**"MongoDB is only here for the prize."** Partly, and flagged in Section 5. It doesn't distort the UX, so it stays.
