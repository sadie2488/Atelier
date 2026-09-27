# Atelier — Devpost draft

[DEMO VIDEO] · Repo: [LINK] · Team: [TEAM]

---

## Tagline

Your closet, styled by color theory: scan a garment, scan yourself, and see the outfit on you.

## Inspiration

Outfit apps tend to fail one of two ways: they guess at color from a product description
("midnight," "true black," "navy" all read as "blue"), or they put a chat box in front of an LLM
and call the result styling advice. We wanted the opposite of both — colors measured as numbers,
a styling engine explainable in one sentence ("these two colors are 150° apart in hue," not "a
model said so"), and the outfit shown on an avatar built from an actual scan of the person
wearing it, not a mannequin.

## What it does

Three steps. **Ingest:** photograph a garment worn by a model, retail-photo style; the backend
segments it into three candidate cutouts — tight, balanced, generous — so a bad automatic guess
never forces a bad save. Pick one, and k-means in CIELAB measures its true primary and secondary
color, given a friendly name from the 949-name xkcd color survey without losing the underlying
numbers. **Recommend:** tap "generate outfit" and six named color-theory strategies — neutral
anchor, everyday-neutral base, analogous, complementary, monochrome-plus-highlight, jacket
"sandwich" — propose combinations, ranked by a deterministic scorer tuned against twelve
human-rated color pairs. **Try it on:** scan yourself once, front-facing with arms slightly away
from your body, for an avatar cut from your own photo, head to feet; a rejected pose gets specific
feedback ("move your arms away from your body"), and auto-capture when standing correctly is in
progress. Tap "see it on me" for an instant local composite; a Gemini-generated try-on follows
seconds later and silently replaces it once verified against the garment's measured colors. A
palette-insights page, on a MongoDB aggregation over the closet, is arriving next.

## How we built it

Python 3.12 and FastAPI, split into independent lanes (vision, styling, avatar) meeting only at a
frozen, contract-first API — Pydantic models generate both the backend's schema validation and
the frontend's TypeScript types, so the two sides can't drift apart. Segmentation and pose
estimation run on MediaPipe; color work is k-means in Lab space with CIEDE2000 distance. The
recommendation engine is pure — no I/O inside a scoring function — so the same closet always
yields the same ranking. The frontend is Next.js on Vercel, calling the backend through a
same-origin rewrite so every request is a relative URL, locally and in production alike. The
backend runs as a single Dockerized service on DigitalOcean App Platform; data and media live in
MongoDB Atlas — documents for items, avatars, and cached renders, GridFS for every image — so a
fresh deploy serves the identical closet with no manual asset step. 130+ offline tests run
against fixtures and recorded responses, never a live call.

## Challenges we ran into

Deploying was harder than building. DigitalOcean's default Python buildpack built but couldn't
see the shared `contract/` package above the backend and lacked MediaPipe's system graphics
libraries — it failed at runtime, not build time, until we switched to a Dockerfile at the repo
root. Even then, the live site 500'd on scan and add-garment because the image was missing
`libEGL.so.1`, a Linux graphics library MediaPipe needs that never shows up on a development
desktop with a real display. Garment isolation had its own edge: retail photos cropped tight
around the waist or hips give the pose model nothing to anchor a bottom's extent to, so several
demo-closet bottoms needed fuller source photos, not a code fix. And try-on verification has a
ceiling — a ΔE2000 check against the measured color caught most bad swaps but couldn't tell dark
indigo jeans from black sweatpants, whose color distance was too small — a garment-identity
problem color alone can't solve.

## Accomplishments we're proud of

A styling recommendation explainable in one sentence, from a scorer that never touches the
network and never changes its mind about the same closet. An avatar that's actually the user, not
a stand-in, in a render pipeline where a slow or failed AI call is invisible. A contract-first
API strict enough that backend and frontend, built on separate lanes, never had a shape mismatch
reach production.

## What we learned

The unglamorous parts — a missing graphics library, a buildpack that builds without working, a
too-tightly-cropped source photo — cost more time than the color math or the styling logic.
Verification isn't correctness: "close enough in color" still lets the wrong garment through when
two garments are close in color. And a UI can hide a failed AI call completely, but only if the
fallback path was built first and treated as the real product.

## What's next

Ship the in-progress palette-insights page. Turn on scan auto-capture once its verification pass
is complete. Extend garment-identity verification past color distance for cases like dark denim
versus black knit. Reshoot the demo-closet photos too tightly cropped for reliable segmentation.

## Built with

Python, FastAPI, Pydantic, MediaPipe, OpenCV, scikit-learn, scikit-image, Next.js, TypeScript,
Tailwind CSS, MongoDB Atlas, GridFS, Docker, DigitalOcean App Platform, Vercel, Google Gemini
(image generation and text explanations), xkcd color survey (color naming), pytest.
