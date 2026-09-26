#!/usr/bin/env python3
"""Validate the whole contract. HUMAN-OWNED. Run from the repo root before freezing:

    python -m contract.check_contract

Checks: every fixture validates against its model; every endpoint has examples; ids are
unique; outfits reference existing items in the right slots; colors agree with their hex
and with colors.json; the fixture closet can satisfy neutral_anchor. Exit 0 = ready to freeze.
"""
import json
import sys
from pathlib import Path

from contract import schemas as S
from contract.enums import (
    MAX_ASSIGNMENT_DELTA_E, NEUTRAL_CHROMA_MAX, SECONDARY_MIN_DELTA_E, Category,
)
from contract.tools.color import color_table, delta_e76, delta_e2000, hex_to_lab, lab_to_lch, nearest_color

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "fixtures"
problems, notes = [], []


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def check(label, model, data):
    try:
        return model.model_validate(data)
    except Exception as e:  # pydantic.ValidationError
        errs = e.errors() if hasattr(e, "errors") else [{"loc": (), "msg": str(e)}]
        for err in errs[:3]:
            where = ".".join(str(x) for x in err["loc"]) or "(model)"
            problems.append(f"{label} {where}: {err['msg']}")


def check_color(label, c):
    lab = hex_to_lab(c.hex)
    if delta_e76(lab, c.lab) > 1.0:
        problems.append(f"{label}: lab {c.lab} doesn't match hex {c.hex} (dE76 {delta_e76(lab, c.lab):.1f})")
    L, C, h = lab_to_lch(c.lab)
    if abs(L - c.lch[0]) > 0.05 or abs(C - c.lch[1]) > 0.05:
        problems.append(f"{label}: lch {c.lch} doesn't match lab {c.lab}")
    elif C > 1 and min(abs(h - c.lch[2]), 360 - abs(h - c.lch[2])) > 0.5:
        problems.append(f"{label}: lch hue {c.lch[2]} doesn't match lab {c.lab}")
    name, family, everyday = nearest_color(c.lab)
    if (c.name, c.family, c.everyday_neutral) != (name, family, everyday):
        problems.append(f"{label}: name/family/everyday_neutral {c.name}/{c.family}/{c.everyday_neutral} "
                        f"but nearest colors.json center gives {name}/{family}/{everyday}")


def check_colors(label, obj):
    check_color(f"{label}.primary_color", obj.primary_color)
    if obj.secondary_color is not None:
        check_color(f"{label}.secondary_color", obj.secondary_color)
        de = delta_e2000(obj.primary_color.lab, obj.secondary_color.lab)
        if de < SECONDARY_MIN_DELTA_E:
            problems.append(f"{label}: secondary only dE2000 {de:.1f} from primary")


def main():
    # thresholds agree with colors.json
    limit, _ = color_table()
    if limit != MAX_ASSIGNMENT_DELTA_E:
        problems.append(f"enums.MAX_ASSIGNMENT_DELTA_E {MAX_ASSIGNMENT_DELTA_E} != colors.json {limit}")

    items = [check(f"items.json[{i}]", S.Item, x) for i, x in enumerate(load(FIX / "items.json"))]
    outfits_resp = check("outfits.json", S.OutfitsGenerateResponse, {"outfits": load(FIX / "outfits.json")})
    avatar = check("avatar.json", S.Avatar, load(FIX / "avatar.json"))
    renders = [check(f"render.json[{i}]", S.RenderJob, r) for i, r in enumerate(load(FIX / "render.json"))]

    # endpoint examples
    names = [S.fixture_name(m, p) for m, p, _, _ in S.ENDPOINTS]
    if len(set(names)) != len(names):
        problems.append(f"fixture_name collisions in ENDPOINTS: {names}")
    api = {}
    for (method, path, req_model, resp_model), name in zip(S.ENDPOINTS, names):
        req_f, resp_f = FIX / "api" / f"{name}.request.json", FIX / "api" / f"{name}.response.json"
        if req_model == "multipart":
            if not req_f.exists():
                problems.append(f"{name}: missing multipart request example")
            else:
                form = dict(load(req_f).get("_multipart", {}))
                if "image" not in form:
                    problems.append(f"{name}: multipart example must include an image part")
                form.pop("image", None)
                if path == "/items/analyze":
                    check(f"api/{req_f.name}", S.AnalyzeForm, form)
                elif form:
                    problems.append(f"{name}: unexpected multipart fields {sorted(form)}")
        elif req_model is not None:
            if req_f.exists():
                api[name + ".request"] = check(f"api/{req_f.name}", req_model, load(req_f))
            else:
                problems.append(f"{name}: missing request example")
        elif req_f.exists():
            problems.append(f"{name}: has a request example but the endpoint takes no body")
        if resp_f.exists():
            api[name] = check(f"api/{resp_f.name}", resp_model, load(resp_f))
        else:
            problems.append(f"{name}: missing response example")
    known = {f"{n}.{k}.json" for n in names for k in ("request", "response")} | {"errors.json"}
    for f in (FIX / "api").glob("*.json"):
        if f.name not in known:
            problems.append(f"api/{f.name}: not an example for any ENDPOINTS entry")
    for i, e in enumerate(load(FIX / "api" / "errors.json")):
        check(f"api/errors.json[{i}]", S.ErrorResponse, e)
    if problems:
        return report()

    # ids and colors
    by_id = {i.id: i for i in items}
    if len(by_id) != len(items):
        problems.append("items.json: duplicate item ids")
    for i in items:
        check_colors(i.id, i)
    for c in api["post_items_analyze"].candidates:
        check_colors(f"analyze candidate {c.index}", c)
    listed = api["get_items"].items
    if {i.id for i in listed} != set(by_id):
        problems.append("get_items response must list exactly the items.json closet")
    if api["get_items_detail"].id not in by_id:
        problems.append("get_items_detail must return an item from items.json")

    # analyze -> save consistency
    analyze, save_req, saved = api["post_items_analyze"], api["post_items_save.request"], api["post_items_save"]
    if save_req.temp_handle != analyze.temp_handle or api["post_items_reject.request"].temp_handle != analyze.temp_handle:
        problems.append("save/reject examples must use the analyze example's temp_handle")
    chosen = analyze.candidates[save_req.candidate_index]
    if (saved.primary_color, saved.secondary_color) != (chosen.primary_color, chosen.secondary_color):
        problems.append("saved item colors must equal the chosen candidate's colors")
    if saved.id in by_id:
        problems.append("saved item must get a fresh slug, not one already in the closet")

    # outfits: references and slots
    outfits = outfits_resp.outfits
    if api["post_outfits_generate"] != outfits_resp:
        problems.append("post_outfits_generate response must equal outfits.json")
    slots = {"top_id": Category.tops, "bottom_id": Category.bottoms, "jacket_id": Category.jackets}
    for o in outfits:
        for field, cat in slots.items():
            ref = getattr(o, field)
            if ref is None:
                continue
            if ref not in by_id:
                problems.append(f"{o.outfit_id}: {field} {ref} is not in items.json")
            elif by_id[ref].category != cat:
                problems.append(f"{o.outfit_id}: {field} {ref} is category {by_id[ref].category.value}, need {cat.value}")

    # S-L3: rung 1 satisfiable (a strict neutral and a chromatic piece across top/bottom)
    tops = [i for i in items if i.category == Category.tops]
    bottoms = [i for i in items if i.category == Category.bottoms]
    if not any(t.primary_color.is_neutral != b.primary_color.is_neutral for t in tops for b in bottoms):
        problems.append("fixture closet cannot satisfy neutral_anchor (need neutral + chromatic across top/bottom)")
    counts = {c.value: sum(i.category == c for i in items) for c in Category}
    for cat, n in {"tops": 3, "bottoms": 3, "jackets": 1}.items():
        if counts[cat] < n:
            problems.append(f"fixture closet has {counts[cat]} {cat}; need at least {n}")
    if not any(i.garment_type.value == "dress" for i in items):
        problems.append("fixture closet needs a dress")

    # avatar and render
    if (api["post_avatar_scan"].model_dump() != avatar.model_dump(exclude={"created_at"})
            or api["get_avatar_detail"] != avatar):
        problems.append("avatar examples must match avatar.json")
    post_render, get_render, render_req = api["post_render"], api["get_render_detail"], api["post_render.request"]
    if render_req.avatar_id != avatar.avatar_id or any(
            r not in by_id for r in (render_req.top_id, render_req.bottom_id, render_req.jacket_id) if r):
        problems.append("post_render request must reference the fixture avatar and closet items")
    if post_render.render_id != get_render.render_id or [post_render, get_render] != renders:
        problems.append("render.json must be [post_render response, get_render_detail response] for one render_id")

    notes.append(f"{len(items)} items {counts}, {sum(i.primary_color.is_neutral for i in items)} strict neutral "
                 f"(chroma < {NEUTRAL_CHROMA_MAX}), {sum(i.primary_color.everyday_neutral for i in items)} everyday neutral")
    notes.append(f"{len(outfits)} outfits, {len(S.ENDPOINTS)} endpoints with examples, contract {S.CONTRACT_VERSION}")
    notes.append("FROZEN: " + ("yes" if (ROOT / "FROZEN").exists() else "no (create contract/FROZEN after review)"))
    return report()


def report():
    for n in notes:
        print("INFO ", n)
    for p in problems:
        print("ERROR", p)
    print("CONTRACT OK" if not problems else f"CONTRACT HAS {len(problems)} PROBLEM(S)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
