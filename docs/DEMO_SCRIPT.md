# Demo script

Run of show for two presenters, about 3 minutes. **A** drives the laptop and does the talking;
**B** runs the scan with the judge, watches the health tab, and calls fallbacks.

Screens: `/scan`, `/closet`, `/stylist`, `/insights`. Backend behavior is in
`coordination/BACKEND_API.md` and `ARCHITECTURE.md`.

---

## Pre-demo checklist (10 minutes before)

- [ ] **Vercel env set and redeployed:** `NEXT_PUBLIC_DEMO_AVATAR_ID=<DEMO_AVATAR_ID>` and
      `NEXT_PUBLIC_DEMO_OUTFITS="<top>,<bottom>[,<jacket>];<top>,<bottom>[,<jacket>]"`. Both are
      `NEXT_PUBLIC_`, so they only take effect after a redeploy.
- [ ] **Demo avatar outfits pre-generated** (both planned outfits, plus the "see it on me" combo
      we will show), e.g. with `backend/avatar/scripts/preview_grid.py --combos ... --only-missing`.
      Open each once and check it by eye.
- [ ] **Backend health:** `<backend-url>/api/health` reads `{"status":"ok","db":"ok"}`. Keep the
      tab open.
- [ ] Flip the hanger-menu **demo avatar** switch on and off once to confirm it works; leave it off.
- [ ] Phone hotspot ready; notifications silenced.
- [ ] **For the judge's scan:** lanyards and badges off, a plain background behind them if
      possible, and they stand head to feet inside the outline.

Placeholders to fill once chosen: demo avatar `<DEMO_AVATAR_ID>`; outfit 1 `<...>`; outfit 2 `<...>`.

---

## Run of show

| # | Who | Click | Say (one line) | If it fails |
|---|---|---|---|---|
| 1 | B | `/scan`: consent, camera, countdown, capture (~7 s) | "We scan you once; your avatar is your real body, cut out of the photo." | Read the correction aloud and retry once; then turn on the **demo avatar** switch and go on. |
| 2 | A | `/closet`: scroll the carousel (wheel works with the cursor over a garment image) | "Every piece was cut off a retail photo and its color measured in Lab space." | Nothing to fail; keep scrolling by hand. |
| 3 | A | Open a garment | "Name, type, and the measured color swatches with friendly names." | Pick another garment. |
| 4 | A | **add to outfit** for a top and a bottom (jacket optional) | "Build a look in the tray: top, bottom, optional jacket." | - |
| 5 | A | **see it on me** | "Now Nano Banana puts those exact pieces on your avatar." (progress bar, ~10-15 s; instant if already generated) | On the calm "try again" note press **try again** (it really regenerates). Second failure: demo avatar switch and repeat. |
| 6 | A | Go to `/stylist` | "The tray's pieces come with us." | - |
| 7 | A | **generate outfit** | "A color-theory scorer picks the outfit; the still image stays until the try-on is ready." | Try again once; else demo avatar switch (planned outfits play in order). |
| 8 | A | Read the explanation and **why this works** | "It tells you why the colors work together, not just that they do." | - |
| 9 | A | **generate outfit** again | "Each press gives a different outfit; after a scan the likely picks are pre-generated, so this is usually instant." | Skip to step 10. |
| 10 | A | **palette insights** (`/insights`) | "And it reads your whole closet's palette." | - |
| 11 | B | Close | "No chat, no free text: measured colors, a deterministic scorer, and a checked try-on." | - |

---

## Talking points (if there is a beat to fill)

- **Try-on:** Nano Banana 2 (`gemini-3.1-flash-image`), prompt v5: replace all clothing, layer
  bottom, then top, then jacket, fit naturally, and never edit the face. Input is the
  background-removed avatar; output is a 3:4 portrait saved with a transparent background.
- **Checked before showing:** garment colors (5 sample points per garment, best match) and a face
  present with a matching skin tone. If a check fails you see "try again", never a wrong image.
- **Vision:** MediaPipe pose and segmentation isolate the garment; k-means in CIELAB gives primary
  and secondary colors; chroma decides "neutral".

---

## Fallbacks in one place

- **Scan rejected twice or no time:** hanger menu, **demo avatar** on. Continue from step 2.
- **Try-on fails:** press **try again** once; then demo avatar.
- **Anything else stalls:** skip to **palette insights**.
- **Backend down (health tab not `ok`):** switch to the hotspot and reload once; if still down,
  say "switching to our backup" and use the demo avatar.

## Operator notes

- `ATELIER_PREWARM_ENABLED=0` turns off background pre-generation after a scan (~35 s of work).
- `GEMINI_IMAGE_MODEL` overrides the try-on model.
- Rollback: tag `demo-stable`.
