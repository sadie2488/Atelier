# tools/

Small command-line tools the lane agents and the PM run. No tool writes to the repo
except `request_dep.py` (its own queue) and `check_cutout.py`/`render_preview.py` (preview
output).

## Working now — no lane code needed

| Tool | Who | What |
|---|---|---|
| `request_dep.py` | all lanes | Queue a dependency request. Lanes may not edit `requirements.txt`; this is the escape hatch that makes that rule workable. |
| `check_media.py` | all lanes, PM | Scan source and response bodies for absolute media URLs. Catches the project's easiest production-only failure. |
| `check_cutout.py` | vision | Every purity, completeness, and structural check on a cutout, plus golden IoU and candidate spread. |
| `check_docs.py` | **PM** | Cross-reference every doc for contradictions. Part of the push gate. |
| `validate_response.py` | all lanes | Validate a response body against the frozen contract. |

## Interface-pinning tools — exit 3 until the lane builds

These import lane code that does not exist yet. Rather than a bare `ImportError`, they
print **the exact module, function, and signature they expect**:

```
NOT BUILT YET: module 'backend.vision.color' does not exist yet

This tool expects:
    # backend/vision/color.py
    def is_neutral(lab: list[float]) -> bool
        """Return True if the colour is strictly neutral, computed from chroma..."""
```

**That signature is the interface.** An agent that runs its tool first learns what to
build, and builds to a shape the PM already knows — which is most of why integration gets
easier. Implement as written; changing the shape means telling the PM.

| Tool | Lane | Expects |
|---|---|---|
| `inspect_image.py` | vision | `backend.vision.color.extract_colors` |
| `run_ingest.py` | vision | `backend.vision.ingest.analyze` |
| `check_neutrals.py` | vision | `backend.vision.color.is_neutral`, `.chroma` |
| `run_expectations.py` | styling | `backend.styling.scorer.score_pair` + `expectations.json` |
| `score_pair.py` | styling | `backend.styling.scorer.score_pair_breakdown` |
| `explain_outfit.py` | styling | `backend.styling.generate.generate_outfits` |
| `gemini_probe.py` | styling | `backend.styling.explain.explain_outfit`, `.fallback_explanation` |
| `render_preview.py` | avatar | `backend.avatar.composite.composite_outfit` |
| `inspect_rig.py` | avatar | `backend.avatar.rig.build_rig` |
| `gen_probe.py` | avatar | `backend.avatar.generate.generate_tryon` |

`_lane.py` is the shared helper behind that message. Not a tool.

## Exit codes

`0` pass · `1` fail · `2` bad usage or missing library · `3` lane code not built yet

The distinction matters: `3` means "not yet", not "broken". A lane seeing 3 should build
the named function, not debug the tool.

## Two that are always worth running

```bash
python tools/check_docs.py      # after ANY doc change; in the push gate
python tools/check_media.py     # before declaring any lane task done
```
