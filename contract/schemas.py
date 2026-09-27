"""Atelier contract v2: data models and API shapes (Pydantic v2). HUMAN-OWNED.

These models are what the API sends and receives. All paths below are relative to the
`/api` prefix. Database-only fields are not part of the contract; modules may store extra
internal fields as long as API output validates against these models.

Media fields are relative URLs, e.g. "/media/items/top_a3f9c2.png", never absolute.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import (
    CANDIDATE_COUNT, NEUTRAL_CHROMA_MAX, OUTFITS_MAX, OUTFITS_MAX_PER_STRATEGY,
    OUTFITS_MAX_SHARING_GARMENT, SECONDARY_MIN_DELTA_E, SLUG_PREFIX, UNMAPPED, VALID_PAIRS,
    CandidateVariant, Category, ErrorCode, GarmentType, RenderStatus, Strategy,
)
from .tools.color import color_table, delta_e2000

CONTRACT_VERSION = "2.2.0"

MEDIA_PATTERN = r"^/media/[a-z]+/[0-9a-zA-Z_.-]+\.png$"
SLUG_PATTERN = r"^[a-z]+_[0-9a-f]{6}$"                  # item id, V-A2
TOP_SLOT_PATTERN = r"^(top|dress)_[0-9a-f]{6}$"          # a tops-category item
BOTTOM_SLOT_PATTERN = r"^bottom_[0-9a-f]{6}$"
JACKET_SLOT_PATTERN = r"^jacket_[0-9a-f]{6}$"
TEMP_HANDLE_PATTERN = r"^tmp_[0-9a-f]{12}$"
AVATAR_ID_PATTERN = r"^avatar_[0-9a-f]{6}$"
OUTFIT_ID_PATTERN = r"^outfit_[0-9a-f]{6}$"
RENDER_ID_PATTERN = r"^render_[0-9a-f]{12}$"             # deterministic cache key of the combination


class Strict(BaseModel):
    """Base: reject unknown fields so mistakes surface instead of passing silently."""
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


def _check_pair(category: Category, garment_type: GarmentType) -> None:
    if garment_type not in VALID_PAIRS[category]:
        allowed = ", ".join(sorted(g.value for g in VALID_PAIRS[category]))
        raise ValueError(f"garment_type {garment_type.value!r} is not valid for category "
                         f"{category.value!r} (allowed: {allowed})")


# ---------------------------------------------------------------- color

class ExtractedColor(Strict):
    """One extracted color (V-C1..V-C5). Numeric values are the truth; names are a lookup."""
    lab: tuple[float, float, float]      # CIE L*a*b* (D65): L 0..100, a/b about -128..127
    lch: tuple[float, float, float]      # L, chroma >= 0, hue degrees [0, 360)
    hex: str = Field(pattern=r"^#[0-9a-f]{6}$")
    name: str                            # colors.json name via nearest CIEDE2000 center, or "unmapped"
    family: str                          # colors.json family of `name`, or "unmapped"
    is_neutral: bool                     # chroma < NEUTRAL_CHROMA_MAX; never from the name
    everyday_neutral: bool               # colors.json flag of `name`; false when unmapped
    display_name: Optional[str] = Field(default=None, max_length=60)  # human-friendly name for the UI:
                                         # nearest contract/color_names.json entry (xkcd survey); display only

    @field_validator("lab")
    @classmethod
    def _lab_range(cls, v):
        L, a, b = v
        if not (0 <= L <= 100 and -128 <= a <= 128 and -128 <= b <= 128):
            raise ValueError("lab out of range")
        return v

    @field_validator("lch")
    @classmethod
    def _lch_range(cls, v):
        L, C, h = v
        if not (0 <= L <= 100 and C >= 0 and 0 <= h < 360):
            raise ValueError("lch out of range")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        if self.is_neutral != (self.lch[1] < NEUTRAL_CHROMA_MAX):
            raise ValueError(f"is_neutral must equal (chroma < {NEUTRAL_CHROMA_MAX})")
        _, table = color_table()
        if self.name == UNMAPPED:
            if self.family != UNMAPPED or self.everyday_neutral:
                raise ValueError("an unmapped color has family 'unmapped' and everyday_neutral false")
        elif self.name not in table:
            raise ValueError(f"name {self.name!r} is not in colors.json (or 'unmapped')")
        else:
            entry = table[self.name]
            if self.family != entry["family"] or self.everyday_neutral != bool(entry["everyday_neutral"]):
                raise ValueError(f"family/everyday_neutral must match colors.json for {self.name!r}")
        return self


def _check_secondary(primary: ExtractedColor, secondary: Optional[ExtractedColor]) -> None:
    if secondary is not None and delta_e2000(primary.lab, secondary.lab) < SECONDARY_MIN_DELTA_E:
        raise ValueError(f"secondary_color must be >= dE2000 {SECONDARY_MIN_DELTA_E} from primary_color")


# ---------------------------------------------------------------- items & ingest

class Item(Strict):
    """A saved closet item. GET /items/{slug}, POST /items/save, and each entry of GET /items."""
    id: str = Field(pattern=SLUG_PATTERN)
    category: Category
    garment_type: GarmentType
    cutout_url: str = Field(pattern=MEDIA_PATTERN)
    primary_color: ExtractedColor
    secondary_color: Optional[ExtractedColor] = None
    retailer_color: Optional[str] = None           # the retailer's original color string
    retailer_item_name: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)   # A3: enrichment; empty at launch
    created_at: datetime

    @model_validator(mode="after")
    def _consistent(self):
        _check_pair(self.category, self.garment_type)
        prefix = SLUG_PREFIX[self.garment_type]
        if not self.id.startswith(prefix + "_"):
            raise ValueError(f"id for garment_type {self.garment_type.value!r} must start with {prefix + '_'!r}")
        _check_secondary(self.primary_color, self.secondary_color)
        return self


class AnalyzeForm(Strict):
    """Form fields of POST /items/analyze (multipart), besides the `image` file part.

    Not a JSON body; published so the backend can validate the form and the frontend can
    type it. An invalid category/garment_type pair is a 400 invalid_request.
    """
    category: Category
    garment_type: GarmentType
    color: Optional[str] = None          # retailer color string -> Item.retailer_color
    item_name: Optional[str] = None      # retailer item name   -> Item.retailer_item_name

    @model_validator(mode="after")
    def _pair(self):
        _check_pair(self.category, self.garment_type)
        return self


class Candidate(Strict):
    index: int = Field(ge=0, le=CANDIDATE_COUNT - 1)
    variant: CandidateVariant
    cutout_url: str = Field(pattern=MEDIA_PATTERN)
    primary_color: ExtractedColor
    secondary_color: Optional[ExtractedColor] = None

    @model_validator(mode="after")
    def _secondary(self):
        _check_secondary(self.primary_color, self.secondary_color)
        return self


_VARIANT_ORDER = [CandidateVariant.tight, CandidateVariant.balanced, CandidateVariant.generous]


class AnalyzeResponse(Strict):
    """POST /items/analyze. Persists nothing; exactly three candidates, index 0..2 in order."""
    temp_handle: str = Field(pattern=TEMP_HANDLE_PATTERN)
    candidates: list[Candidate] = Field(min_length=CANDIDATE_COUNT, max_length=CANDIDATE_COUNT)

    @model_validator(mode="after")
    def _ordered(self):
        if [c.index for c in self.candidates] != list(range(CANDIDATE_COUNT)):
            raise ValueError("candidates must have index 0, 1, 2 in order")
        if [c.variant for c in self.candidates] != _VARIANT_ORDER:
            raise ValueError("candidate variants must be tight, balanced, generous in order")
        return self


class SaveRequest(Strict):
    """POST /items/save. category/garment_type/retailer fields were captured at analyze."""
    temp_handle: str = Field(pattern=TEMP_HANDLE_PATTERN)
    candidate_index: int = Field(ge=0, le=CANDIDATE_COUNT - 1)


SaveResponse = Item


class RejectRequest(Strict):
    """POST /items/reject. Nothing persists; the rejection is logged."""
    temp_handle: str = Field(pattern=TEMP_HANDLE_PATTERN)


class RejectResponse(Strict):
    ok: Literal[True]


class ItemListResponse(Strict):
    """GET /items?category=tops|bottoms|jackets. Stable order: created_at, newest first."""
    items: list[Item]

    @model_validator(mode="after")
    def _ordered(self):
        times = [i.created_at for i in self.items]
        if times != sorted(times, reverse=True):
            raise ValueError("items must be ordered by created_at, newest first")
        if len({i.id for i in self.items}) != len(self.items):
            raise ValueError("item ids must be unique")
        return self


# ---------------------------------------------------------------- outfits

class Outfit(Strict):
    """bottom + (top or dress) + optional jacket (S-O1..S-O3)."""
    outfit_id: str = Field(pattern=OUTFIT_ID_PATTERN)   # stable within a response
    strategy: Strategy
    top_id: str = Field(pattern=TOP_SLOT_PATTERN)       # a tops-category item (shirt or dress)
    bottom_id: str = Field(pattern=BOTTOM_SLOT_PATTERN)
    jacket_id: Optional[str] = Field(default=None, pattern=JACKET_SLOT_PATTERN)
    explanation: str = Field(min_length=1)              # may be the per-strategy static fallback
    score: float = Field(ge=0, le=1)                    # higher is better

    @model_validator(mode="after")
    def _sandwich(self):
        if self.strategy == Strategy.sandwich and self.jacket_id is None:
            raise ValueError("a sandwich outfit requires a jacket_id")
        return self


class OutfitsGenerateRequest(Strict):
    """POST /outfits/generate. The body may be {} (limit defaults to 5)."""
    limit: int = Field(default=OUTFITS_MAX, ge=1, le=OUTFITS_MAX)


class OutfitsGenerateResponse(Strict):
    """Up to 5 outfits, best first. Fewer (or none, for an unsatisfiable closet) is normal."""
    outfits: list[Outfit] = Field(max_length=OUTFITS_MAX)

    @model_validator(mode="after")
    def _selection(self):
        o = self.outfits
        if len({x.outfit_id for x in o}) != len(o):
            raise ValueError("outfit_id must be unique within a response")
        if len({(x.top_id, x.bottom_id, x.jacket_id) for x in o}) != len(o):
            raise ValueError("outfits must be distinct combinations")
        scores = [x.score for x in o]
        if scores != sorted(scores, reverse=True):
            raise ValueError("outfits must be ordered by score, best first")
        per_strategy = Counter(x.strategy for x in o)
        if per_strategy and max(per_strategy.values()) > OUTFITS_MAX_PER_STRATEGY:
            raise ValueError(f"at most {OUTFITS_MAX_PER_STRATEGY} outfits per strategy")
        per_garment = Counter(g for x in o for g in (x.top_id, x.bottom_id))  # jackets exempt
        if per_garment and max(per_garment.values()) > OUTFITS_MAX_SHARING_GARMENT:
            raise ValueError(f"at most {OUTFITS_MAX_SHARING_GARMENT} outfits may share a top or bottom")
        return self


# ---------------------------------------------------------------- avatar & render

class AvatarScanResponse(Strict):
    """POST /avatar/scan (multipart: image). A pose failure is 422 pose_rejected with an actionable message."""
    avatar_id: str = Field(pattern=AVATAR_ID_PATTERN)
    wireframe_url: str = Field(pattern=MEDIA_PATTERN)
    avatar_url: str = Field(pattern=MEDIA_PATTERN)


class Avatar(AvatarScanResponse):
    """GET /avatar/{avatar_id}"""
    created_at: datetime


class RenderRequest(Strict):
    """POST /render"""
    avatar_id: str = Field(pattern=AVATAR_ID_PATTERN)
    top_id: str = Field(pattern=TOP_SLOT_PATTERN)
    bottom_id: str = Field(pattern=BOTTOM_SLOT_PATTERN)
    jacket_id: Optional[str] = Field(default=None, pattern=JACKET_SLOT_PATTERN)


class RenderJob(Strict):
    """POST /render and GET /render/{render_id}. local_url is always present and correct;
    generated_url is set exactly when status is done."""
    render_id: str = Field(pattern=RENDER_ID_PATTERN)
    status: RenderStatus
    local_url: str = Field(pattern=MEDIA_PATTERN)
    generated_url: Optional[str] = Field(default=None, pattern=MEDIA_PATTERN)

    @model_validator(mode="after")
    def _generated(self):
        if (self.status == RenderStatus.done) != (self.generated_url is not None):
            raise ValueError("generated_url is set exactly when status is done")
        return self


# ---------------------------------------------------------------- insights (contract 2.2.0)

class FamilyShare(Strict):
    """One colors.json family's presence in the closet, by item primary color."""
    family: str
    count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)                  # count / item_count
    hex: str = Field(pattern=r"^#[0-9a-f]{6}$")        # representative color (mean Lab of its items)


class PaletteSwatch(Strict):
    item_id: str = Field(pattern=SLUG_PATTERN)
    category: Category
    hex: str = Field(pattern=r"^#[0-9a-f]{6}$")
    display_name: Optional[str] = Field(default=None, max_length=60)
    family: str


class VersatileItem(Strict):
    item_id: str = Field(pattern=SLUG_PATTERN)
    outfit_count: int = Field(ge=0)                    # outfits it appears in among generated candidates


class PaletteInsights(Strict):
    """GET /insights/palette: closet-wide color summary for the palette page (styling lane)."""
    item_count: int = Field(ge=0)
    neutral_share: float = Field(ge=0, le=1)           # share of items whose primary is_neutral
    families: list[FamilyShare]                        # most common first
    swatches: list[PaletteSwatch]                      # one per item, newest first
    missing_families: list[str]                        # colors.json families with no item
    insights: list[str] = Field(max_length=6)          # plain-language observations, each one sentence
    most_versatile: list[VersatileItem] = Field(max_length=3)


# ---------------------------------------------------------------- misc

class HealthResponse(Strict):
    status: Literal["ok"]
    db: Literal["ok"]


class ErrorBody(Strict):
    code: ErrorCode
    message: str = Field(min_length=1)


class ErrorResponse(Strict):
    """Every 4xx/5xx response body."""
    error: ErrorBody


# ---------------------------------------------------------------- endpoint registry
# (method, path under /api, request model | "multipart" | None, success response model)
# check_contract.py verifies each has example fixtures in contract/fixtures/api/.

ENDPOINTS = [
    ("GET",  "/health",             None,                   HealthResponse),
    ("POST", "/items/analyze",      "multipart",            AnalyzeResponse),
    ("POST", "/items/save",         SaveRequest,            SaveResponse),
    ("POST", "/items/reject",       RejectRequest,          RejectResponse),
    ("GET",  "/items",              None,                   ItemListResponse),
    ("GET",  "/items/{slug}",       None,                   Item),
    ("POST", "/outfits/generate",   OutfitsGenerateRequest, OutfitsGenerateResponse),
    ("POST", "/avatar/scan",        "multipart",            AvatarScanResponse),
    ("GET",  "/avatar/{avatar_id}", None,                   Avatar),
    ("POST", "/render",             RenderRequest,          RenderJob),
    ("GET",  "/render/{render_id}", None,                   RenderJob),
    ("GET",  "/insights/palette",   None,                   PaletteInsights),
]

# Every model published in schema.json (the frontend generates TypeScript from it).
API_MODELS = [
    ExtractedColor, Item, AnalyzeForm, Candidate, AnalyzeResponse, SaveRequest, RejectRequest,
    RejectResponse, ItemListResponse, Outfit, OutfitsGenerateRequest, OutfitsGenerateResponse,
    AvatarScanResponse, Avatar, RenderRequest, RenderJob, HealthResponse, ErrorResponse,
    FamilyShare, PaletteSwatch, VersatileItem, PaletteInsights,
]


def fixture_name(method: str, path: str) -> str:
    """Path parameters are dropped; a path that has one gets a `_detail` suffix.

    'GET', '/items'          -> 'get_items'
    'GET', '/items/{slug}'   -> 'get_items_detail'
    'POST', '/items/analyze' -> 'post_items_analyze'
    """
    segs = path.strip("/").split("/")
    parts = [p for p in segs if not p.startswith("{")]
    if len(parts) != len(segs):
        parts.append("detail")
    return "_".join([method.lower(), *parts])
