# Golden Reference Log

The 20 frozen cutout references that Vision's V2 output is measured against at
>=0.85 IoU.

**Only the PM re-blesses references, and only after a human pass.** A lane subagent
never regenerates references to make its own output pass — that would make the bar
meaningless.

## Current set

| Blessed | By | Fixtures | Reason |
|---|---|---|---|
| — | — | — | *(initial pass not yet run)* |

## How to run the initial pass

1. Dispatch vision V2 so it produces three candidates per fixture.
2. A human opens all three per fixture and picks the best.
3. Copy the chosen cutouts to `fixtures/golden/<filename>.png`.
4. Record the date and who did it in the table above.
5. From then on, `check_cutout.py --golden` measures IoU automatically.

## How to regenerate

Only when segmentation legitimately improves and a human has re-picked. Add a row
with the date, who, which fixtures changed, and why.
