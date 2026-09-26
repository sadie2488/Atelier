#!/usr/bin/env python3
"""Validate the whole contract. HUMAN-OWNED. Run from the repo root before freezing:

    python3 -m contract.check_contract

Checks: every fixture validates against its model; ids and references are consistent;
colors match their hex values; the fixture closet can form outfits; every endpoint has
examples; the template body is laid out sensibly. Exit 0 = ready to freeze.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from contract import schemas as S
from contract.enums import NEUTRAL_CHROMA_MAX
from contract.tools.color import delta_e76, hex_to_lab, lab_to_lch

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "fixtures"
problems, notes = [], []


def load(p: Path):
    return json.loads(p.read_text())


def check(label, model, data):
    try:
        return model.model_validate(data)
    except Exception as e:  # pydantic.ValidationError
        errs = e.errors() if hasattr(e, "errors") else [{"loc": (), "msg": str(e)}]
        for err in errs[:3]:
            where = ".".join(str(x) for x in err["loc"]) or "(model)"
            problems.append(f"{label} {where}: {err['msg']}")


def outfit_shape_ok(cats):
    c = Counter(cats)
    base = (c["top"] == 1 and c["bottom"] == 1 and c["dress"] == 0) or (c["dress"] == 1 and c["top"] == 0 and c["bottom"] == 0)
    return base and c["shoes"] == 1 and c["outerwear"] <= 1 and c["accessory"] == 0


def main():
    garments = [check(f"garments.json[{i}]", S.Garment, g) for i, g in enumerate(load(FIX / "garments.json"))]
    avatar = check("avatar.json", S.Avatar, load(FIX / "avatar.json"))
    outfits = [check(f"outfits.json[{i}]", S.Outfit, o) for i, o in enumerate(load(FIX / "outfits.json"))]
    render = check("render.json", S.Render, load(FIX / "render.json"))
    template = check("template_body.json", S.TemplateBody, load(ROOT / "template_body.json"))

    # endpoint examples
    for method, path, req_model, resp_model in S.ENDPOINTS:
        name = S.fixture_name(method, path)
        req_f, resp_f = FIX / "api" / f"{name}.request.json", FIX / "api" / f"{name}.response.json"
        if req_model == "multipart":
            if not req_f.exists():
                problems.append(f"{name}: missing multipart request example")
        elif req_model is not None:
            check(f"api/{req_f.name}", req_model, load(req_f)) if req_f.exists() else problems.append(f"{name}: missing request example")
        if resp_model is not None:
            check(f"api/{resp_f.name}", resp_model, load(resp_f)) if resp_f.exists() else problems.append(f"{name}: missing response example")
    for i, e in enumerate(load(FIX / "api" / "errors.json")):
        check(f"api/errors.json[{i}]", S.ErrorResponse, e)
    if problems:
        return report()

    by_id = {g.id: g for g in garments}
    if len(by_id) != len(garments):
        problems.append("duplicate garment ids")

    # colors: hex, lab, lch agree; neutral flag agrees
    for g in garments:
        for c in g.colors:
            lab = hex_to_lab(c.hex)
            if delta_e76(lab, c.lab) > 1.0:
                problems.append(f"{g.id}: color {c.hex} lab {c.lab} doesn't match its hex (dE {delta_e76(lab, c.lab):.1f})")
            if delta_e76(lab_to_lch(c.lab)[:2], c.lch[:2]) > 1.0:
                problems.append(f"{g.id}: color {c.hex} lch doesn't match its lab")

    # closet composition: enough to build outfits and exercise the scorer
    cats = Counter(g.category.value for g in garments)
    need = {"top": 3, "bottom": 3, "shoes": 2, "dress": 1, "outerwear": 1}
    for cat, n in need.items():
        if cats[cat] < n:
            problems.append(f"fixture closet has {cats[cat]} {cat}(s); need at least {n}")
    if not any(g.is_neutral for g in garments):
        problems.append("fixture closet needs at least one neutral garment")
    if sum(g.pattern.value != "solid" for g in garments) < 2:
        problems.append("fixture closet needs at least two patterned garments")
    if not any(g.ownership.value == "catalog" for g in garments):
        problems.append("fixture closet needs catalog items")

    # outfits: references, shape, needs_purchase
    for o in outfits:
        missing = [i for i in o.item_ids if i not in by_id]
        if missing:
            problems.append(f"outfit {o.id}: unknown items {missing}")
            continue
        if not outfit_shape_ok([by_id[i].category.value for i in o.item_ids]):
            problems.append(f"outfit {o.id}: not top+bottom+shoes or dress+shoes (+ optional outerwear)")
        catalog = {i for i in o.item_ids if by_id[i].ownership.value == "catalog"}
        if set(o.needs_purchase) != catalog:
            problems.append(f"outfit {o.id}: needs_purchase must list exactly its catalog items")
    if render and (render.avatar_id != avatar.id or render.outfit_id not in {o.id for o in outfits}):
        problems.append("render.json must reference the fixture avatar and an existing outfit")

    # template body layout sanity
    t = template
    if t.head_slot.y + t.head_slot.h > t.anchors["top"].y + 20:
        problems.append("template: head_slot should end above the top anchor")
    if t.shoes_area.y < t.anchors["bottom"].y + t.anchors["bottom"].h - 20:
        problems.append("template: shoes_area should start below the bottom anchor")
    if set(t.anchors) - set(t.layer_order):
        problems.append("template: every anchor must appear in layer_order")

    notes.append(f"{len(garments)} garments ({dict(cats)}), "
                 f"{sum(g.ownership.value == 'catalog' for g in garments)} catalog, "
                 f"{sum(g.is_neutral for g in garments)} neutral (chroma < {NEUTRAL_CHROMA_MAX})")
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
