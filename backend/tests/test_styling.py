"""Styling lane tests. Offline, fixture-driven (S-I2): the items collection may be empty for
this lane's whole duration, so every route test overrides `get_db` with an in-memory fake
instead of touching Mongo.

The 12 scorer expectations in `backend/styling/expectations.json` are the specification
(S-C5) once the human provides that file; until it exists, this module tests the DECISIONS.md
rules directly and every expectation test is skipped, never faked.
"""
from __future__ import annotations

import copy
import json
import random
from collections import Counter
from pathlib import Path

import pytest

from backend.db import get_db
from backend.main import app
from contract.enums import Strategy
from contract.schemas import Outfit, OutfitsGenerateResponse

from backend.styling import select as select_mod
from backend.styling.explain import explain, fallback_explanation
from backend.styling.scorer import score_color_pair, score_items
from backend.styling.strategies import generate_candidates

EXPECTATIONS_PATH = Path(__file__).resolve().parents[1] / "styling" / "expectations.json"


# --------------------------------------------------------------------------- color fixtures

def _color(l, c, h, family="blue", is_neutral=False, everyday_neutral=False, name="test"):
    import math
    a = c * math.cos(math.radians(h))
    b = c * math.sin(math.radians(h))
    return {
        "lab": (l, a, b), "lch": (l, c, h), "hex": "#000000", "name": name,
        "family": family, "is_neutral": is_neutral, "everyday_neutral": everyday_neutral,
    }


def _item(item_id, primary, secondary=None, attributes=None):
    return {
        "id": item_id, "primary_color": primary, "secondary_color": secondary,
        "attributes": attributes or {},
    }


NEUTRAL_WHITE = _color(95, 2, 90, family="achromatic", is_neutral=True, name="white")
NEUTRAL_BLACK = _color(15, 1, 280, family="achromatic", is_neutral=True, name="black")
CHROMATIC_RED = _color(45, 57, 32, family="red", name="red")
CHROMATIC_GREEN = _color(48, 48, 147, family="green", name="green")
BASE_NAVY = _color(22, 28, 282, family="blue", everyday_neutral=True, name="navy")
BASE_OLIVE = _color(44, 28, 106, family="green", everyday_neutral=True, name="olive")
BASE_CAMEL = _color(60, 39, 71, family="warm_light", everyday_neutral=True, name="camel")
ANALOGOUS_A = _color(50, 40, 30, family="orange", name="orange")
ANALOGOUS_B = _color(50, 40, 55, family="yellow", name="yellow")
COMPLEMENT_A = _color(45, 10, 30, family="orange", name="tan")     # low chroma
COMPLEMENT_B = _color(45, 45, 210, family="blue", name="blue")


# ------------------------------------------------------------------------------- S-C: scorer

def test_scorer_uses_numeric_hue_not_name():
    """S-C2: hue/chroma from lch, never from name -- two colors named differently but with
    identical lch score identically to two colors sharing the same names."""
    a = _color(50, 50, 10, family="red", name="scarlet")
    b = _color(50, 50, 10, family="red", name="crimson")
    c = _color(50, 50, 10, family="red", name="scarlet")
    d = _color(50, 50, 10, family="red", name="crimson")
    assert score_color_pair(a, b) == score_color_pair(c, d)


def test_secondary_color_scores_at_reduced_weight():
    """S-C3: a secondary color's contribution is weighted less than the primary's."""
    top = _item("top_1", CHROMATIC_RED)
    bottom_no_secondary = _item("bottom_1", CHROMATIC_GREEN)
    bottom_with_bad_secondary = _item("bottom_2", CHROMATIC_GREEN, secondary=COMPLEMENT_B)

    base = score_items(top, bottom_no_secondary)
    with_secondary = score_items(top, bottom_with_bad_secondary)
    # adding a secondary must move the score, but not by the full primary-primary delta
    primary_only_delta = abs(score_color_pair(CHROMATIC_RED, CHROMATIC_GREEN) - score_color_pair(CHROMATIC_RED, COMPLEMENT_B))
    assert with_secondary != base
    assert abs(with_secondary - base) < primary_only_delta


def test_missing_attributes_never_penalized():
    """S-C4: an item without enrichment attributes must never score worse than an otherwise
    identical item that has them -- the scorer must not read `attributes` at all."""
    plain = _item("top_1", CHROMATIC_RED, attributes={})
    enriched = _item("top_1", CHROMATIC_RED, attributes={"sleeve": "long", "source": "model"})
    other = _item("bottom_1", BASE_NAVY)
    assert score_items(plain, other) == score_items(enriched, other)


def test_missing_secondary_color_never_penalized():
    """S-C4, applied to secondary_color: absent is neutral, not a penalty, relative to a
    same-scoring partner."""
    top_no_secondary = _item("top_1", CHROMATIC_RED)
    top_with_neutral_secondary = _item("top_2", CHROMATIC_RED, secondary=NEUTRAL_WHITE)
    bottom = _item("bottom_1", BASE_NAVY)
    # a neutral secondary only ever helps or is flat -- never drags the score down
    assert score_items(top_with_neutral_secondary, bottom) >= score_items(top_no_secondary, bottom)


# ---------------------------------------------------------------------- S-S: strategy rungs

def test_neutral_anchor_always_eligible_for_strict_neutral_plus_chromatic():
    """S-S2 rung 1: a strict neutral + a chromatic piece is neutral_anchor, regardless of
    which family the chromatic piece belongs to."""
    top = _item("top_1", NEUTRAL_WHITE)
    bottom = _item("bottom_1", CHROMATIC_RED)
    [(strategy, t, b, jacket, score)] = list(generate_candidates([top], [bottom], []))
    assert strategy == Strategy.neutral_anchor
    assert jacket is None
    assert 0.0 <= score <= 1.0


def test_everyday_neutral_base_pairs_base_with_true_chromatic():
    """S-S2 rung 2: an everyday-neutral base (navy/denim/olive/camel/beige/brown) paired with
    a true chromatic (not itself a base, not strict neutral) is everyday_neutral_base."""
    top = _item("top_1", BASE_NAVY)
    bottom = _item("bottom_1", CHROMATIC_RED)
    [(strategy, *_rest)] = list(generate_candidates([top], [bottom], []))
    assert strategy == Strategy.everyday_neutral_base


def test_two_everyday_neutral_bases_are_not_rung_1_or_2():
    """Two everyday-neutral bases (both navy and olive, say) satisfy neither rung 1 (neither
    is strict-neutral) nor rung 2 (neither is a 'true' chromatic partner)."""
    top = _item("top_1", BASE_NAVY)
    bottom = _item("bottom_1", BASE_OLIVE)
    results = list(generate_candidates([top], [bottom], []))
    strategies = {r[0] for r in results}
    assert Strategy.neutral_anchor not in strategies
    assert Strategy.everyday_neutral_base not in strategies


def test_analogous_strategy():
    """S-S2 rung 3: hue angle <= 40 degrees apart, both true chromatics -> analogous."""
    top = _item("top_1", ANALOGOUS_A)
    bottom = _item("bottom_1", ANALOGOUS_B)
    [(strategy, *_rest)] = list(generate_candidates([top], [bottom], []))
    assert strategy == Strategy.analogous


def test_complementary_strategy_requires_low_chroma_piece():
    """S-S2 rung 3: hue angle 150-210 degrees apart AND at least one low-chroma piece."""
    top = _item("top_1", COMPLEMENT_A)
    bottom = _item("bottom_1", COMPLEMENT_B)
    [(strategy, *_rest)] = list(generate_candidates([top], [bottom], []))
    assert strategy == Strategy.complementary

    # two high-chroma pieces 180 degrees apart: complementary's chroma condition is unmet,
    # and it must stay silent (S-S3), not degrade into a different label. (Reusing the
    # original low-chroma `top` here would trivially satisfy "at least one low-chroma piece"
    # again, so both pieces must be high-chroma to actually exercise this branch.)
    high_chroma_orange = _color(45, 55, 30, family="orange", name="bright_orange")
    high_chroma_blue = _color(45, 55, 210, family="blue", name="bright_blue")
    top2 = _item("top_2", high_chroma_orange)
    bottom2 = _item("bottom_2", high_chroma_blue)
    results = list(generate_candidates([top2], [bottom2], []))
    assert results == [] or all(r[0] != Strategy.complementary for r in results)


def test_monochrome_highlight_strategy_eligible_with_wide_l_spread():
    """S-S2 rung 4: same family, L* spread >= 20 -> monochrome_highlight."""
    top = _item("top_1", _color(70, 30, 260, family="blue", name="light_blue"))
    bottom = _item("bottom_1", _color(25, 25, 260, family="blue", name="navy_blue"))  # spread 45
    [(strategy, *_rest)] = list(generate_candidates([top], [bottom], []))
    assert strategy == Strategy.monochrome_highlight


def test_monochrome_highlight_silent_when_l_spread_too_narrow():
    """S-S3: same family but a flat L* spread (< 20) does not qualify -- stays silent rather
    than degrading into a different strategy."""
    top = _item("top_1", _color(50, 30, 260, family="blue", name="blue_a"))
    bottom = _item("bottom_1", _color(55, 30, 260, family="blue", name="blue_b"))  # spread 5
    results = list(generate_candidates([top], [bottom], []))
    assert results == []


def test_monochrome_highlight_allows_one_optional_accent_jacket():
    """S-S2 rung 4: the optional accent piece is the existing single optional jacket layer --
    a monochrome_highlight pair is offered both without and with a compatible jacket."""
    top = _item("top_1", _color(70, 30, 260, family="blue", name="light_blue"))
    bottom = _item("bottom_1", _color(25, 25, 260, family="blue", name="navy_blue"))
    jacket = _item("jacket_1", NEUTRAL_BLACK)
    results = list(generate_candidates([top], [bottom], [jacket]))
    assert all(strategy == Strategy.monochrome_highlight for strategy, *_ in results)
    jacket_ids = {r[3]["id"] if r[3] else None for r in results}
    assert None in jacket_ids
    assert "jacket_1" in jacket_ids


_SANDWICH_TOP = _item("top_1", _color(45, 40, 250, family="blue", name="sandwich_top"))
_SANDWICH_BOTTOM = _item("bottom_1", _color(40, 35, 150, family="green", name="sandwich_bottom"))
_SANDWICH_JACKET = _item("jacket_1", _color(50, 30, 140, family="green", name="sandwich_jacket"))


def test_sandwich_requires_jacket_family_matching_bottom_and_contrasting_top():
    """S-S2 rung 5: jacket and bottom share a family; the top's family differs (contrasts)."""
    # Sanity check: the base top+bottom pair alone must not already resolve under rungs 1-4,
    # or the ladder-priority rule (a pair labeled once) would keep sandwich from ever firing.
    assert _classify_pair_for_test(_SANDWICH_TOP, _SANDWICH_BOTTOM) is None

    [(strategy, top, bottom, jacket, score)] = list(
        generate_candidates([_SANDWICH_TOP], [_SANDWICH_BOTTOM], [_SANDWICH_JACKET])
    )
    assert strategy == Strategy.sandwich
    assert jacket["id"] == "jacket_1"
    assert 0.0 <= score <= 1.0


def test_sandwich_dormant_with_no_suitable_jacket():
    """S-S2 rung 5 / S-S3: a closet with no jacket at all leaves sandwich dormant -- correct
    behavior, not a bug -- since the strategy needs a jacket for its third color slot."""
    results = list(generate_candidates([_SANDWICH_TOP], [_SANDWICH_BOTTOM], []))
    assert results == []


def test_sandwich_silent_when_jacket_family_does_not_match_bottom():
    """S-S3: a jacket whose family differs from the bottom's does not form a 'bread' pair."""
    mismatched_jacket = _item("jacket_2", _color(50, 30, 30, family="orange", name="orange_jacket"))
    results = list(generate_candidates([_SANDWICH_TOP], [_SANDWICH_BOTTOM], [mismatched_jacket]))
    assert results == []


def test_sandwich_silent_when_top_shares_family_with_jacket_and_bottom():
    """S-S3: if the top is the same family as the jacket/bottom, there is no contrast -- this
    is a monochrome look, not a sandwich, and sandwich must stay silent rather than mislabel it."""
    same_family_top = _item("top_2", _color(45, 40, 150, family="green", name="green_top"))
    results = list(generate_candidates([same_family_top], [_SANDWICH_BOTTOM], [_SANDWICH_JACKET]))
    assert results == []


def _classify_pair_for_test(top, bottom):
    from backend.styling.strategies import _classify_pair
    return _classify_pair(top, bottom)


def test_strategy_stays_silent_when_ineligible():
    """S-S3: a pair matching none of the implemented rungs yields no candidate at all."""
    top = _item("top_1", BASE_NAVY)
    bottom = _item("bottom_1", BASE_CAMEL)  # both bases, unrelated families, > analogous band
    results = list(generate_candidates([top], [bottom], []))
    # BASE_NAVY (h=282) vs BASE_CAMEL (h=71): far apart, not complementary band either
    assert results == []


def test_dress_is_a_top_no_special_case():
    """S-O1/S-O2: a dress (category tops, garment_type dress) is treated exactly like a shirt
    -- no exclusion logic, it just occupies the top slot."""
    dress = _item("dress_1", NEUTRAL_WHITE)
    bottom = _item("bottom_1", CHROMATIC_RED)
    [(strategy, top, b, jacket, score)] = list(generate_candidates([dress], [bottom], []))
    assert top["id"] == "dress_1"
    assert strategy == Strategy.neutral_anchor


def test_jacket_is_optional_layer():
    """S-O3: jackets are optional -- a base pairing is offered both without and with a
    compatible jacket."""
    top = _item("top_1", NEUTRAL_WHITE)
    bottom = _item("bottom_1", CHROMATIC_RED)
    jacket = _item("jacket_1", NEUTRAL_BLACK)
    results = list(generate_candidates([top], [bottom], [jacket]))
    jacket_ids = {r[3]["id"] if r[3] else None for r in results}
    assert None in jacket_ids
    assert "jacket_1" in jacket_ids


# ------------------------------------------------------------------------------- S-L: select

def test_select_max_per_strategy_and_sharing_cap():
    """S-L1: max 2 per strategy, max 2 outfits sharing a top or bottom."""
    candidates = [
        {"strategy": Strategy.neutral_anchor, "top_id": "top_1", "bottom_id": f"bottom_{i}",
         "jacket_id": None, "score": 0.9 - i * 0.01}
        for i in range(5)
    ]
    chosen = select_mod.select_outfits(candidates, limit=5)
    assert len(chosen) == 2  # capped by OUTFITS_MAX_SHARING_GARMENT on top_1, not by strategy


def test_select_returns_fewer_rather_than_padding():
    """S-L2: only 2 valid candidates in a closet that could hold 5 -> returns 2."""
    candidates = [
        {"strategy": Strategy.neutral_anchor, "top_id": "top_1", "bottom_id": "bottom_1",
         "jacket_id": None, "score": 0.9},
        {"strategy": Strategy.everyday_neutral_base, "top_id": "top_2", "bottom_id": "bottom_2",
         "jacket_id": None, "score": 0.8},
    ]
    assert len(select_mod.select_outfits(candidates, limit=5)) == 2


def test_select_empty_candidates_returns_empty():
    assert select_mod.select_outfits([], limit=5) == []


def test_select_orders_best_score_first():
    candidates = [
        {"strategy": Strategy.neutral_anchor, "top_id": "top_1", "bottom_id": "bottom_1",
         "jacket_id": None, "score": 0.5},
        {"strategy": Strategy.neutral_anchor, "top_id": "top_2", "bottom_id": "bottom_2",
         "jacket_id": None, "score": 0.9},
    ]
    chosen = select_mod.select_outfits(candidates, limit=5)
    assert [c["score"] for c in chosen] == [0.9, 0.5]


def test_outfit_id_is_deterministic():
    id_a = select_mod.make_outfit_id("top_1", "bottom_1", None)
    id_b = select_mod.make_outfit_id("top_1", "bottom_1", None)
    id_c = select_mod.make_outfit_id("top_1", "bottom_1", "jacket_1")
    assert id_a == id_b
    assert id_a != id_c
    assert id_a.startswith("outfit_") and len(id_a) == len("outfit_") + 6


# ---------------------------------------------------------------- S4: variety in selection

def _fixture_candidates(items):
    """Build the same candidate dicts the route builds, straight from a raw items list."""
    tops = [i for i in items if i["category"] == "tops"]
    bottoms = [i for i in items if i["category"] == "bottoms"]
    jackets = [i for i in items if i["category"] == "jackets"]
    return [
        {
            "strategy": strategy, "top": top, "bottom": bottom, "jacket": jacket,
            "top_id": top["id"], "bottom_id": bottom["id"],
            "jacket_id": jacket["id"] if jacket else None,
            "score": max(0.0, min(1.0, score)),
        }
        for strategy, top, bottom, jacket, score in generate_candidates(tops, bottoms, jackets)
    ]


def _assert_selection_rules_hold(chosen):
    strategy_counts = Counter(c["strategy"] for c in chosen)
    assert all(n <= select_mod.W.OUTFITS_MAX_PER_STRATEGY for n in strategy_counts.values())
    garment_counts = Counter()
    for c in chosen:
        garment_counts[c["top_id"]] += 1
        garment_counts[c["bottom_id"]] += 1
    assert all(n <= select_mod.W.OUTFITS_MAX_SHARING_GARMENT for n in garment_counts.values())
    # best-score-first
    scores = [c["score"] for c in chosen]
    assert scores == sorted(scores, reverse=True)


def test_variety_different_seeds_yield_different_top_outfit(fixture_items):
    """Two calls with different seeds on the real fixture closet pick different top-ranked
    outfits when the pool has tied/near-tied alternatives (the fixture closet does: several
    neutral_anchor combos score exactly 0.9, but only 2 fit under the per-strategy cap)."""
    candidates = _fixture_candidates(fixture_items)
    chosen_a = select_mod.select_outfits(candidates, limit=5, rng=random.Random(0))
    chosen_b = select_mod.select_outfits(candidates, limit=5, rng=random.Random(2))
    top_a = (chosen_a[0]["top_id"], chosen_a[0]["bottom_id"], chosen_a[0]["jacket_id"])
    top_b = (chosen_b[0]["top_id"], chosen_b[0]["bottom_id"], chosen_b[0]["jacket_id"])
    assert top_a != top_b
    _assert_selection_rules_hold(chosen_a)
    _assert_selection_rules_hold(chosen_b)


def test_variety_selection_rules_hold_for_50_seeds(fixture_items):
    """Every existing selection rule (S-L1: caps, best-first) holds no matter which seed
    drives the weighted-random sampling."""
    candidates = _fixture_candidates(fixture_items)
    for seed in range(50):
        chosen = select_mod.select_outfits(candidates, limit=5, rng=random.Random(seed))
        assert len(chosen) > 0  # S-L3: rung 1 is satisfiable in the fixture closet
        assert len(chosen) <= 5
        _assert_selection_rules_hold(chosen)


def test_variety_tiny_closet_with_one_valid_outfit_still_returns_it():
    """A closet with exactly one eligible combo returns that one outfit, for any seed."""
    top = _item("top_1", NEUTRAL_WHITE)
    bottom = _item("bottom_1", CHROMATIC_RED)
    candidates = [
        {"strategy": strategy, "top_id": top["id"], "bottom_id": bottom["id"],
         "jacket_id": jacket["id"] if jacket else None, "score": max(0.0, min(1.0, score))}
        for strategy, _t, _b, jacket, score in generate_candidates([top], [bottom], [])
    ]
    for seed in (0, 1, 2, 3, 4):
        chosen = select_mod.select_outfits(candidates, limit=5, rng=random.Random(seed))
        assert len(chosen) == 1
        assert chosen[0]["top_id"] == "top_1"
        assert chosen[0]["bottom_id"] == "bottom_1"


def test_variety_empty_closet_returns_empty_for_any_seed():
    for seed in (0, 1, 2):
        assert select_mod.select_outfits([], limit=5, rng=random.Random(seed)) == []


def test_variety_avoids_immediate_repeat_when_alternatives_exist(fixture_items):
    """previous_ids down-weights/excludes last response's combos; with the fixture closet's
    generous pool, a second call excluding the first call's outfit_ids should not reproduce
    the same top-ranked outfit every time."""
    candidates = _fixture_candidates(fixture_items)
    first = select_mod.select_outfits(candidates, limit=5, rng=random.Random(0))
    previous_ids = {
        select_mod.make_outfit_id(c["top_id"], c["bottom_id"], c["jacket_id"]) for c in first
    }
    second = select_mod.select_outfits(
        candidates, limit=5, rng=random.Random(0), previous_ids=previous_ids
    )
    second_ids = {
        select_mod.make_outfit_id(c["top_id"], c["bottom_id"], c["jacket_id"]) for c in second
    }
    # excluded outright since the fixture pool has enough fresh alternatives to fill the limit
    assert not (second_ids & previous_ids)
    _assert_selection_rules_hold(second)


def test_variety_rng_is_injectable_and_route_uses_unseeded_rng():
    """S4 determinism contract: passing the same seed twice reproduces the same selection."""
    candidates = [
        {"strategy": Strategy.neutral_anchor, "top_id": f"top_{i}", "bottom_id": f"bottom_{i}",
         "jacket_id": None, "score": 0.9 - i * 0.001}
        for i in range(10)
    ]
    chosen_a = select_mod.select_outfits(candidates, limit=2, rng=random.Random(42))
    chosen_b = select_mod.select_outfits(candidates, limit=2, rng=random.Random(42))
    assert chosen_a == chosen_b

    from backend.routes import outfits as outfits_route
    assert isinstance(outfits_route._rng, random.Random)


# --------------------------------------------------------------------------- S-E: explanations

def test_gemini_fallback_fires_and_is_covered(monkeypatch):
    """S-E3: the static fallback fires on any Gemini failure and is exercised by a test, not
    merely written. Here it fires because no API key is configured."""
    from backend import config
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    text = explain(Strategy.neutral_anchor, _item("top_1", NEUTRAL_WHITE), _item("bottom_1", CHROMATIC_RED), None)
    assert text == fallback_explanation(Strategy.neutral_anchor)
    assert text  # non-empty


def test_gemini_fallback_fires_on_error(monkeypatch):
    """S-E4: even if a key is configured, an exception during the call must not propagate or
    return an empty explanation -- the fallback fires instead."""
    from backend import config
    from backend.styling import explain as explain_mod
    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key-for-test")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated Gemini failure")

    monkeypatch.setattr(explain_mod, "_gemini_explain", _boom)
    text = explain(Strategy.complementary, _item("top_1", NEUTRAL_WHITE), _item("bottom_1", CHROMATIC_RED), None)
    assert text == fallback_explanation(Strategy.complementary)


def test_every_strategy_has_a_fallback():
    for strategy in Strategy:
        assert fallback_explanation(strategy)


def test_generate_endpoint_does_not_wait_per_outfit_on_slow_gemini(monkeypatch, client, fake_db, fixture_items):
    """S-E4 (latency): explanations are requested concurrently on ONE shared deadline, not
    sequentially -- a Gemini call that hangs past the budget on every outfit must not multiply
    the response latency by the outfit count. Offline: `_gemini_explain` is monkeypatched to
    sleep, never hits the network."""
    import time

    from backend import config
    from backend.styling import explain as explain_mod
    from backend.styling import weights as W

    monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key-for-test")

    def _slow(strategy, top, bottom, jacket):
        time.sleep(W.EXPLAIN_BUDGET_SECONDS + 5)
        return "should never be seen: this call was too slow"

    monkeypatch.setattr(explain_mod, "_gemini_explain", _slow)
    # Each outfit's color combo must be unique so the in-process cache can't short-circuit a
    # repeat and mask the timeout behavior this test exists to check.
    explain_mod._cache.clear()

    fake_db["items"] = _FakeCollection(fixture_items)

    start = time.monotonic()
    resp = client.post("/api/outfits/generate", json={})
    elapsed = time.monotonic() - start

    assert resp.status_code == 200
    body = resp.json()
    validated = OutfitsGenerateResponse.model_validate(body)
    assert len(validated.outfits) > 0

    assert elapsed < W.EXPLAIN_BUDGET_SECONDS + 1.0

    for outfit in validated.outfits:
        assert outfit.explanation == fallback_explanation(outfit.strategy)


# --------------------------------------------------------------------------------- endpoint

class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *args, **kwargs):
        return [copy.deepcopy(d) for d in self._docs]


@pytest.fixture
def fake_db(client):
    """Overrides get_db (S-I1/S-I2: this lane never touches real Mongo). Seed per test with
    `fake_db["items"] = _FakeCollection(docs)`."""
    holder = {"items": _FakeCollection([])}
    app.dependency_overrides[get_db] = lambda: holder
    yield holder
    app.dependency_overrides.pop(get_db, None)


def test_generate_empty_closet_returns_empty_outfits(client, fake_db):
    resp = client.post("/api/outfits/generate", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"outfits": []}
    OutfitsGenerateResponse.model_validate(body)


def test_generate_fixture_closet_is_non_empty_and_contract_valid(client, fake_db, fixture_items):
    """Exit criteria: non-empty for the fixture closet (neutral_anchor is satisfiable), and
    the whole response validates against the frozen contract."""
    fake_db["items"] = _FakeCollection(fixture_items)
    resp = client.post("/api/outfits/generate", json={})
    assert resp.status_code == 200
    body = resp.json()
    validated = OutfitsGenerateResponse.model_validate(body)
    assert len(validated.outfits) > 0
    assert len(validated.outfits) <= 5
    for outfit in validated.outfits:
        Outfit.model_validate(outfit.model_dump())


def test_generate_strips_db_only_fields(client, fake_db, fixture_items):
    """Route must strip `_id` and other DB-only fields (e.g. `anchors`) before validating."""
    docs = copy.deepcopy(fixture_items)
    for doc in docs:
        doc["_id"] = "507f1f77bcf86cd799439011"
        doc["anchors"] = {"shoulder": [0, 0]}
    fake_db["items"] = _FakeCollection(docs)
    resp = client.post("/api/outfits/generate", json={})
    assert resp.status_code == 200
    OutfitsGenerateResponse.model_validate(resp.json())


def test_generate_no_body_uses_default_limit(client, fake_db, fixture_items):
    fake_db["items"] = _FakeCollection(fixture_items)
    resp = client.post("/api/outfits/generate")
    assert resp.status_code == 200
    OutfitsGenerateResponse.model_validate(resp.json())


def test_generate_respects_limit(client, fake_db, fixture_items):
    fake_db["items"] = _FakeCollection(fixture_items)
    resp = client.post("/api/outfits/generate", json={"limit": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["outfits"]) <= 1


# ---------------------------------------------------------------------------- I: insights

from contract.schemas import PaletteInsights
from backend.styling.insights import compute_insights


def test_insights_empty_closet_is_contract_valid(client, fake_db):
    resp = client.get("/api/insights/palette")
    assert resp.status_code == 200
    body = resp.json()
    validated = PaletteInsights.model_validate(body)
    assert validated.item_count == 0
    assert validated.neutral_share == 0.0
    assert validated.families == []
    assert validated.swatches == []
    assert validated.insights == []
    assert validated.most_versatile == []
    assert len(validated.missing_families) > 0  # every colors.json family is "missing"


def test_insights_fixture_closet_is_contract_valid(client, fake_db, fixture_items):
    fake_db["items"] = _FakeCollection(fixture_items)
    resp = client.get("/api/insights/palette")
    assert resp.status_code == 200
    body = resp.json()
    validated = PaletteInsights.model_validate(body)
    assert validated.item_count == len(fixture_items)
    assert len(validated.swatches) == len(fixture_items)
    newest_first = sorted(fixture_items, key=lambda it: it["created_at"], reverse=True)
    assert [s["item_id"] for s in body["swatches"]] == [it["id"] for it in newest_first]
    assert len(validated.insights) <= 6
    assert len(validated.most_versatile) <= 3


class _FakeCollectionWithAggregate(_FakeCollection):
    """Same as the local find-only fake, but also supports the family-count aggregation
    pipeline the route tries first (both the aggregate and Python-fallback paths must
    produce identical `families` output)."""

    def aggregate(self, pipeline):
        assert pipeline == [{"$group": {"_id": "$primary_color.family", "count": {"$sum": 1}}}]
        counts: dict[str, int] = {}
        for doc in self._docs:
            fam = doc["primary_color"]["family"]
            counts[fam] = counts.get(fam, 0) + 1
        return [{"_id": fam, "count": n} for fam, n in counts.items()]


def test_insights_aggregate_and_fallback_paths_agree(client, fake_db, fixture_items):
    """The route tries db['items'].aggregate(...) for family counts and falls back to
    counting in Python from find() when the collection doesn't support it (the shared test
    fake never does). Both must produce the same `families` output for the same closet."""
    fake_db["items"] = _FakeCollection(fixture_items)  # no aggregate -> Python fallback
    fallback_body = client.get("/api/insights/palette").json()

    fake_db["items"] = _FakeCollectionWithAggregate(fixture_items)  # aggregate path
    aggregate_body = client.get("/api/insights/palette").json()

    assert aggregate_body["families"] == fallback_body["families"]
    assert aggregate_body["item_count"] == fallback_body["item_count"]


def test_compute_insights_pure_empty_list():
    """compute_insights is a pure function: no DB, no route needed."""
    result = compute_insights([])
    PaletteInsights.model_validate(result)
    assert result["item_count"] == 0
    assert result["families"] == []
    assert result["missing_families"]  # every family missing


# ------------------------------------------------------------------------- expectations.json

def _load_expectations():
    if not EXPECTATIONS_PATH.exists():
        return None
    return json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _load_expectations() or [None])
def test_scorer_expectations(case):
    """S-C5: the 12 scorer expectations are the specification. Skips (does not fake-pass)
    until backend/styling/expectations.json exists."""
    if case is None:
        pytest.skip("backend/styling/expectations.json does not exist yet (owed by the human)")
    a, b = case["a"], case["b"]
    score = score_color_pair(a, b)
    assert score == pytest.approx(case["expected_score"], abs=case.get("tolerance", 0.05))


# ------------------------------------------------------------- colour-dressing guide (S5)

from contract.tools.color import hex_to_lab
from backend.styling import pairing_guide as PG


def test_guide_color_denim_special_case():
    light_jeans = hex_to_lab("#9fb6d1")
    indigo_jeans = hex_to_lab("#2c3a5c")
    black_jeans = hex_to_lab("#1c1c1e")
    assert PG.guide_color(light_jeans, "pants") == "light blue"
    assert PG.guide_color(indigo_jeans, "pants") == "navy"
    assert PG.guide_color(black_jeans, "pants") == "black"
    assert PG.guide_color(light_jeans, "shorts") == "light blue"


def test_guide_color_nearest_swatch():
    assert PG.guide_color(hex_to_lab("#ffffff"), "shirt") == "white"
    assert PG.guide_color(hex_to_lab("#d32027"), "shirt") == "red"
    assert PG.guide_color(hex_to_lab("#f4c2c2"), "shirt") == "pink"
    assert PG.guide_color(hex_to_lab("#1b2a5a"), "shirt") == "navy"
    assert PG.guide_color(hex_to_lab("#5a3a2e"), "shirt") == "brown"


def test_pair_quality_rows_and_symmetry():
    assert PG.pair_quality("pink", "navy") == "complementary"
    assert PG.pair_quality("light blue", "orange") == "complementary"
    assert PG.pair_quality("navy", "yellow") == "complementary"
    assert PG.pair_quality("red", "pink") == "tonal"
    assert PG.pair_quality("light blue", "navy") == "tonal"
    assert PG.pair_quality("orange", "grey") == "neutral"
    assert PG.pair_quality("yellow", "purple") == "none"
    names = list(PG.GUIDE_SWATCHES)
    for a in names:
        for b in names:
            assert PG.pair_quality(a, b) == PG.pair_quality(b, a)


def test_guide_bonus_ranks_listed_pair_above_unlisted():
    from backend.styling import weights as W
    assert W.GUIDE_COMPLEMENTARY_BONUS > 0 > W.GUIDE_UNLISTED_PENALTY
    jeans = {"id": "bottom_1", "garment_type": "pants", "primary_color": {"lab": hex_to_lab("#9fb6d1")}}
    red = {"id": "top_1", "garment_type": "shirt", "primary_color": {"lab": hex_to_lab("#d32027")}}
    assert PG.pair_adjustment(red, jeans) == W.GUIDE_COMPLEMENTARY_BONUS
    assert PG.guide_sentence(red, jeans) == "Light-wash denim pairs well with red."


def test_guide_sentence_only_for_listed_pairs():
    pink = {"garment_type": "shirt", "primary_color": {"lab": hex_to_lab("#f4c2c2")}}
    navy_skirt = {"garment_type": "skirt", "primary_color": {"lab": hex_to_lab("#1b2a5a")}}
    yellow = {"garment_type": "shirt", "primary_color": {"lab": hex_to_lab("#fdd835")}}
    purple = {"garment_type": "skirt", "primary_color": {"lab": hex_to_lab("#7a4a63")}}
    assert PG.guide_sentence(pink, navy_skirt) == "Pink and navy are an easy classic pairing."
    assert PG.guide_sentence(yellow, purple) is None


def test_seasonal_classifier_synthetic_palettes():
    soft_autumn = [hex_to_lab(h) for h in ("#8a7a5c", "#9c6b4e", "#7d7a52", "#a08466")]
    deep_winter = [hex_to_lab(h) for h in ("#1b2a5a", "#3b1f4a", "#0f3b3a", "#5a1030")]
    light_summer = [hex_to_lab(h) for h in ("#c9e0f2", "#d8c8e8", "#bfd8e0", "#c8d4ee")]
    bright_spring = [hex_to_lab(h) for h in ("#f05a28", "#fdd835", "#ff7f50", "#e0a000")]
    assert PG.classify_season(soft_autumn)["season"] == "soft autumn"
    assert PG.classify_season(deep_winter)["season"] == "deep winter"
    assert PG.classify_season(light_summer)["season"] == "light summer"
    assert PG.classify_season(bright_spring)["season"] in ("bright spring", "true spring")
    assert PG.classify_season([hex_to_lab("#f05a28")]) is None


def test_insights_guide_suggestion_uses_bottoms(fixture_items):
    result = compute_insights(fixture_items)
    PaletteInsights.model_validate(result)
    assert len(result["insights"]) <= 6
