# Human checklist

Everything here needs a person. The agents cannot start, or cannot be verified, until
these land. The slots already exist — fill them in.

Ordered by what blocks the most.

---

## 1. The fixture set — blocks Vision entirely

**Slot:** `fixtures/images/` + `fixtures/MANIFEST.csv` (20 rows, pre-stubbed)

20 retail product images of garments worn by models. Fill in each row: filename,
category, garment_type, the retailer's color string and item name verbatim, and your
own eyeball of the true color as hex.

Three things that matter more than they look:

- **Neutral pose.** Front-facing, arms down. Every pose-region strategy assumes it.
- **Vary skin tone deliberately.** Segmentation that only works on light skin passes
  every automated check and fails real users. This is the one bias the tooling cannot
  catch for you.
- **A dress is `category: tops`, `garment_type: dress`.** Not its own category.

Also gather the 10 deliberately broken cases listed in `fixtures/images/README.md` —
they can overlap the 20.

Until this exists, V2 and V4 have no bar and the golden pass cannot run.

---

## 2. The Gemini spike — 30 minutes, decides A7

**No slot needed. Just run it:**

```bash
python tools/gen_probe.py <your photo> <a garment image>
```

One photo, one garment, one call. Then look at the output and judge two things: is it
still recognizably the same person, and is the garment still recognizable?

This is the single highest-value 30 minutes available. The whole generated-try-on
approach rests on output quality nobody has seen. If identity drift is severe, cut A7 —
that is a fine outcome, and the local composite is the product either way. **Knowing at
hour 2 is worth enormously more than knowing at hour 28.**

---

## 3. Golden references — blocks Vision's automated bar

**Slot:** `fixtures/golden/` + `contract/GOLDEN_LOG.md`

After V2 produces three candidates per fixture, a human picks the best one per image.
Those become the frozen references, and from then on the bar is automated at ≥0.85 IoU.

You pay this cost once. Until then, "is the cutout good" needs a person every time.

---

## 4. The 12 scorer expectations — blocks Styling's bar

**Slot:** `backend/styling/expectations.json`

Re-verify each of the 12 against the **current** item shape (primary + secondary color,
the everyday-neutral flag) and a calibrated `colors.json`. They were verified under an
older shape.

Format:

```json
[{"id": "E1", "item_a": {...}, "item_b": {...},
  "expected_score": 0.82, "note": "why this is the right answer"}]
```

`run_expectations.py` explains this too if you run it early.

Do this **after** step 5, or you will verify against numbers that then change.

---

## 5. Calibrate `colors.json`

**Slot:** `contract/colors.json` — values are in place but are estimates, not measurements

Check the Lab centers against real garments. Two known weak boundaries:

- **beige / tan / camel** crowd each other
- **denim / navy / blue** overlap badly (flagged as accepted in V-C7)

Once step 4 is verified against these values, changing a center invalidates it.

---

## 6. Pre-scanned backup avatar

**Slot:** task A8

A scan of yourselves plus a seeded closet, tested **on the deployed URL, on cellular,
with real keys**, reachable in one action. Pre-cache its renders so even a dead API
looks live.

It is a backup, not the plan. Rehearse live capture.

---

## 7. Frontend items

- Confirm the frontend has read `coordination/BACKEND_API.md`
- Consent line before face photos are uploaded (you said you have this covered)
- The one-action backup-avatar trigger

---

## Start tonight

1 and 2. Everything else can wait a few hours; those two cannot.
