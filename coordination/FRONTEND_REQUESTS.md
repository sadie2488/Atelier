# Frontend → Backend

**Written by: the frontend agent/session only.** The backend PM reads this every dispatch
cycle and responds by editing `coordination/BACKEND_API.md` — **not** by editing this file.
Two writers on one file is how you get merge conflicts between two laptops.

**Cadence:** append an entry the moment you are blocked or notice a mismatch, then push. Do
not batch requests; a blocked frontend and a backend that does not know is the most expensive
state in this project.

---

## How to use this

Append a new row. Newest at the top. Leave `Status` and `Resolution` blank — the PM fills
those in when it responds, and points you at the `BACKEND_API.md` change.

**Types:**

- `BLOCKED` — you cannot proceed. The PM treats these first.
- `MISMATCH` — the API behaves differently than `BACKEND_API.md` says. Include what you sent,
  what you expected, what you got.
- `REQUEST` — you need a field, an endpoint, or a behavior that does not exist.
- `QUESTION` — a behavior is unspecified and you do not want to guess.
- `FYI` — a frontend decision the backend should know about.

**When you are blocked, keep building against a mock** shaped like `BACKEND_API.md` and flag
it here. Do not wait idle, and do not silently invent a different shape — an undeclared mock
that diverges from the real API is worse than being blocked, because nobody finds out until
integration.

---

## Open

| # | Type | Raised | Detail | Status | Resolution |
|---|---|---|---|---|---|
| — | — | — | *(none yet)* | — | — |

## Resolved

| # | Type | Detail | Resolution |
|---|---|---|---|
| — | — | *(none yet)* | — |

---

## Scope boundary

The two halves are split cleanly. Raise anything that crosses this line **here, before
building it** — do not implement across the boundary and do not assume the other side has it
covered.

**Frontend owns:** camera capture and the pose outline overlay, client-side downscaling, swipe
lists and their rendering, the generate button, positioning garments at index 0, the metadata
detail panel, polling and the image swap, all loading and degraded states, the backup-avatar
shortcut, the consent line.

**Backend owns:** every endpoint, segmentation and cutouts, color extraction, scoring and
outfit selection, avatar assembly, local compositing, generation and its verification, caching,
all media files.

**Grey areas — raise as `QUESTION`, do not decide unilaterally:**

- Which side enforces an image size or dimension limit
- Whether a value is computed server-side or derived in the client
- Anything that would mean the same logic existing on both sides

If you find yourself writing color logic, scoring logic, or garment placement logic in the
frontend, stop and raise it. That work belongs to a backend lane and duplicating it will
diverge.
