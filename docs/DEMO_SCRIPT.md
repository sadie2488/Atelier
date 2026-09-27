# Demo script

A 2–3 minute live run for two presenters. **A** drives the laptop/phone and talks through the
flow; **B** watches the health tab, times the beats, and jumps in during the "under the hood"
section. Adjust names to whoever is presenting.

Screens referenced: `/`, `/scan`, `/closet`, `/add-item`, `/stylist`. Backend behavior
referenced throughout is documented in `coordination/BACKEND_API.md` and `ARCHITECTURE.md`.

---

## Pre-demo checklist (do this 5–10 minutes before you go on)

- [ ] **Run one full warm-up cycle** on the deployed URL: hit `/api/health`, scan or load the
      backup avatar, generate an outfit, and render it once. The first request after a deploy is
      slow because MediaPipe loads its models — never let that slow request happen live.
- [ ] **Keep a health tab open** at `<backend-url>/api/health`. It should read
      `{"status":"ok","db":"ok"}`. This tab is how you tell "the backend is down" from "the venue
      Wi-Fi is down" in half a second.
- [ ] **Turn on a phone hotspot** and know how to switch to it fast. Venue Wi-Fi is the single
      most common demo failure; don't discover it's down mid-sentence.
- [ ] **Have the backup avatar URL ready in a tab or bookmark:** `/scan?backup=avatar_f709dc`.
      This drops straight into a pre-scanned avatar with cached, completed try-ons, skipping the
      camera entirely.
- [ ] Confirm the demo closet is seeded (a handful of garments already in `/closet`) so the
      swipe lists aren't empty before the live add-item beat.
- [ ] Silence notifications on the presenting device.

---

## The script

**0:00 — Open on `/closet`.**
"This is Atelier — a closet app that understands color the way a stylist does, not by name, but
by measurement." Show the swipe lists (tops, bottoms) already populated from the seeded demo
closet.

**0:15 — Point at one item's swatch.**
Tap an item to open its detail panel. "Every garment here was cut off a retail photo
automatically, and its color was measured in Lab space — that swatch next to the retailer's
name is the actual extracted color, not a guess from the product description."

**0:35 — Tap "Generate outfit."**
The top-ranked outfit's garments jump to position 0 of the tops and bottoms lists. "That's a
deterministic color-theory scorer choosing this pairing — no LLM in the ranking path, so it's
the same result every time on the same closet."

**0:55 — Move to `/stylist` with that outfit selected.**
Tap **See it on me**. The local composite (the avatar in the chosen outfit) appears essentially
instantly. "This is a live composite over an avatar cut from my own scan — it's already
correct, and it's the guaranteed path even if everything past this point fails."

**1:15 — While the background generation runs, narrate rather than wait.**
"In the background, Gemini is generating a photorealistic try-on of this exact combination —
that usually takes about ten seconds. We don't make you stare at a spinner: what you're looking
at right now is already a correct answer." (Use this beat for the "under the hood" aside below
if the timing lines up.)

**1:30–1:45 — The swap.**
The generated image quietly replaces the local composite. "Notice nothing flashed or reloaded —
that swap only happens after we've checked the generated image's garment colors against the
measured colors from the closet. If that check ever fails, you'd never know; it just keeps the
local composite."

**1:50 — Move to `/add-item`.**
Photograph (or upload a prepared photo of) one garment live. "Now we prove the ingestion
pipeline works live, not just on the seeded closet." Walk through the three candidate cutouts
appearing (tight / balanced / generous), pick one, save it.

**2:20 — Back to `/closet`.**
The newly added garment appears at the top of its list. "That garment is real now — same
pipeline, same color measurement, same scorer eligibility as everything else in the closet."

**2:35–3:00 — Close.**
"Every piece of this — the cutout, the color, the outfit logic, the avatar, the render — is a
deterministic or verified step. The only place an LLM writes free text is a one-line style
explanation, and even that has a fallback. Nothing here is a chatbot; it's a pipeline."

---

## 30-second "under the hood" aside

Use this if you have a beat to fill (e.g., while the Gemini try-on renders) or at the end if
time allows:

"Under the hood: a retail photo goes through MediaPipe pose and segmentation to isolate just the
garment off the model — three candidate cutouts, tuned for tight, balanced, and generous crops,
and knit patterns are kept intact rather than flattened out. K-means clustering in CIELAB gives
each garment a primary and secondary color; a color-name table and a chroma threshold turn that
into a human-readable name and a neutral flag. On the styling side, a handful of named
color-theory strategies — a neutral anchor, an everyday-neutral base, analogous, complementary —
feed a pure, deterministic scorer tuned against twelve human-rated color pairs, so the ranking
never changes for the same closet. And the whole thing is backed by 122 offline tests, so
none of this is being demoed for the first time tonight."

---

## If something fails

**Render is slow or never finishes.**
Keep talking over the local composite — it's already correct and already on screen. Do not
apologize or refresh. If you want to fill time, use the "under the hood" aside above. The local
composite is the guaranteed path by design; treat a slow or missing generated swap as expected,
not as a bug.

**The scan gets rejected.**
Read the correction message aloud exactly as shown ("move your arms away from your body," etc.)
— it's built to be actionable, and reading it out loud reframes the rejection as the app working
correctly rather than failing. If a second attempt also fails or you're short on time, switch to
the backup avatar: navigate to `/scan?backup=avatar_f709dc` and continue the script from there
without breaking stride.

**The backend is down (health tab stops reading `ok`).**
Don't debug live. Switch immediately to the phone hotspot and reload once. If it's still down,
say so plainly ("we're switching to our backup path") and continue on the backup avatar and the
already-seeded closet — every combination cached for `avatar_f709dc` renders instantly with no
generation needed, so the two-stage swap beat still works even fully offline from your primary
network.

**A live add-item photo fails or times out.**
Don't retry more than once on stage. Fall back to a garment already in the seeded closet and
say "here's one we added earlier the same way" — the pipeline story doesn't depend on the photo
being taken in front of the judges.
