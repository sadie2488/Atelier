"""Closet app contract: data models and API shapes (Pydantic v2). HUMAN-OWNED (lane A).

These models are what the API sends and receives. Database-only fields (for example
the raw Gemini response) are not part of the contract; each module may store extra
internal fields as long as the API output validates against these models.

IDs are 24-character lowercase hex strings (MongoDB ObjectIds rendered as text).
Image fields are URLs relative to the backend, e.g. "/media/cutouts/<id>.png".
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import (
    FORMALITY_MAX, FORMALITY_MIN, MAX_COLORS, MIN_COLORS, NEUTRAL_CHROMA_MAX,
    OUTFIT_MAX_ITEMS, OUTFIT_MIN_ITEMS, REASON_MAX_CHARS, RECOMMEND_MAX_LIMIT,
    Category, ErrorCode, GarmentStatus, HeadSource, Ownership, Pattern, ReasonSource,
    SegmentClass, Source,
)

CONTRACT_VERSION = "1.0.0"

ObjectId = str  # documented alias; validated by ID_PATTERN
ID_PATTERN = r"^[0-9a-f]{24}$"
MEDIA_PATTERN = r"^/media/[a-z]+/[0-9a-zA-Z_.-]+\.png$"


class Strict(BaseModel):
    """Base: reject unknown fields so mistakes surface instead of passing silently."""
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# ---------------------------------------------------------------- geometry & color

class Rect(Strict):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class Color(Strict):
    """One color cluster of a garment, computed on opaque cutout pixels only."""
    lab: tuple[float, float, float]      # CIE L*a*b* (D65): L 0..100, a/b about -128..127
    lch: tuple[float, float, float]      # L, chroma >= 0, hue degrees 0..360
    hex: str = Field(pattern=r"^#[0-9a-f]{6}$")
    weight: float = Field(gt=0, le=1)    # share of garment pixels

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


# ---------------------------------------------------------------- stored entities

class Garment(Strict):
    id: ObjectId = Field(pattern=ID_PATTERN)
    user_id: str
    photo_id: Optional[ObjectId] = Field(default=None, pattern=ID_PATTERN)
    source: Source
    ownership: Ownership
    status: GarmentStatus
    is_guest: bool = False
    cutout_url: str = Field(pattern=MEDIA_PATTERN)
    bbox: Rect                                   # in the preprocessed source image
    colors: list[Color] = Field(min_length=MIN_COLORS, max_length=MAX_COLORS)
    is_neutral: bool
    category: Optional[Category] = None          # required when status == ready
    subcategory: Optional[str] = Field(default=None, max_length=40)
    pattern: Optional[Pattern] = None            # required when status == ready
    formality: Optional[int] = Field(default=None, ge=FORMALITY_MIN, le=FORMALITY_MAX)
    style_tags: list[str] = Field(default_factory=list, max_length=8)
    user_edited: bool = False
    created_at: datetime

    @model_validator(mode="after")
    def _consistent(self):
        weights = [c.weight for c in self.colors]
        if weights != sorted(weights, reverse=True):
            raise ValueError("colors must be sorted by weight, largest first")
        if sum(weights) > 1.0001:
            raise ValueError("color weights sum to more than 1")
        if self.is_neutral != (self.colors[0].lch[1] < NEUTRAL_CHROMA_MAX):
            raise ValueError(f"is_neutral must equal (dominant chroma < {NEUTRAL_CHROMA_MAX})")
        if self.status == GarmentStatus.ready and None in (self.category, self.pattern, self.formality):
            raise ValueError("a ready garment needs category, pattern, and formality")
        if self.ownership == Ownership.catalog and (self.is_guest or self.source != Source.flatlay):
            raise ValueError("catalog items are flat-lay and never guest items")
        return self


class Avatar(Strict):
    id: ObjectId = Field(pattern=ID_PATTERN)
    user_id: str
    head_url: str = Field(pattern=MEDIA_PATTERN)
    head_source: HeadSource
    is_guest: bool = False
    created_at: datetime


class ScoreBreakdown(Strict):
    """Each component is 0..1, higher is better."""
    hue: float = Field(ge=0, le=1)
    pattern: float = Field(ge=0, le=1)
    formality: float = Field(ge=0, le=1)


class Outfit(Strict):
    id: ObjectId = Field(pattern=ID_PATTERN)
    user_id: str
    anchor_id: ObjectId = Field(pattern=ID_PATTERN)
    item_ids: list[ObjectId] = Field(min_length=OUTFIT_MIN_ITEMS, max_length=OUTFIT_MAX_ITEMS)
    needs_purchase: list[ObjectId] = Field(default_factory=list)   # catalog items in this outfit
    rank: int = Field(ge=1)                                        # 1 = best
    rule_score: float = Field(ge=0, le=1)
    breakdown: ScoreBreakdown
    reason: str = Field(min_length=1, max_length=REASON_MAX_CHARS)
    reason_source: ReasonSource
    model: Optional[str] = None                                    # e.g. the Gemini model id; None for template
    created_at: datetime

    @model_validator(mode="after")
    def _consistent(self):
        if self.anchor_id not in self.item_ids:
            raise ValueError("anchor_id must be one of item_ids")
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("item_ids must be unique")
        if not set(self.needs_purchase) <= set(self.item_ids):
            raise ValueError("needs_purchase must be a subset of item_ids")
        if (self.reason_source == ReasonSource.template) != (self.model is None):
            raise ValueError("model is set exactly when reason_source is llm")
        return self


class Render(Strict):
    id: ObjectId = Field(pattern=ID_PATTERN)
    avatar_id: ObjectId = Field(pattern=ID_PATTERN)
    outfit_id: ObjectId = Field(pattern=ID_PATTERN)
    image_url: str = Field(pattern=MEDIA_PATTERN)
    created_at: datetime


class TemplateBody(Strict):
    """contract/template_body.json: where things go on the drawn body (pixels)."""
    version: str
    image: str                          # "placeholder" until the team's drawing exists
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    head_slot: Rect
    anchors: dict[Literal["top", "bottom", "dress", "outerwear"], Rect]
    shoes_area: Rect
    arms_overlay: Optional[str] = None  # PNG drawn over garments; None for the placeholder
    layer_order: list[Literal["bottom", "dress", "top", "outerwear", "arms"]]

    @model_validator(mode="after")
    def _inside(self):
        rects = {"head_slot": self.head_slot, "shoes_area": self.shoes_area, **self.anchors}
        for name, r in rects.items():
            if r.x + r.w > self.width or r.y + r.h > self.height:
                raise ValueError(f"{name} falls outside the {self.width}x{self.height} canvas")
        return self


# ---------------------------------------------------------------- API: requests & responses

class ErrorBody(Strict):
    code: ErrorCode
    message: str


class ErrorResponse(Strict):
    """Every 4xx/5xx response body."""
    error: ErrorBody


class HealthResponse(Strict):
    status: Literal["ok"]
    contract_version: str


class AvatarCreateResponse(Strict):
    """POST /avatar  (multipart: image=<face capture>, is_guest=<bool>)"""
    avatar: Avatar


class Candidate(Strict):
    """One detected garment region, shown to the user to tap before saving."""
    candidate_id: str = Field(pattern=r"^c[0-9]+$")
    segment_class: SegmentClass
    cutout_url: str = Field(pattern=MEDIA_PATTERN)
    bbox: Rect


class IngestResponse(Strict):
    """POST /ingest  (multipart: image, source=scan|flatlay, ownership=owned|catalog, is_guest)

    Always returns candidates; nothing is saved until /ingest/{photo_id}/select.
    A flat-lay returns exactly one candidate. The original image is deleted after this call.
    """
    photo_id: ObjectId = Field(pattern=ID_PATTERN)
    source: Source
    candidates: list[Candidate] = Field(min_length=1)


class SelectRequest(Strict):
    """POST /ingest/{photo_id}/select"""
    candidate_ids: list[str] = Field(min_length=1)
    category_overrides: dict[str, Category] = Field(default_factory=dict)  # candidate_id -> category

    @model_validator(mode="after")
    def _overrides_known(self):
        if not set(self.category_overrides) <= set(self.candidate_ids):
            raise ValueError("category_overrides keys must be selected candidate_ids")
        return self


class SelectResponse(Strict):
    """Classification runs synchronously; each garment comes back ready or needs_review."""
    garments: list[Garment] = Field(min_length=1)


class GarmentListResponse(Strict):
    """GET /garments?ownership=owned|catalog&include_guest=true|false"""
    garments: list[Garment]


class GarmentPatch(Strict):
    """PATCH /garments/{id}  (only the fields being changed; sets user_edited)"""
    category: Optional[Category] = None
    subcategory: Optional[str] = Field(default=None, max_length=40)
    pattern: Optional[Pattern] = None
    formality: Optional[int] = Field(default=None, ge=FORMALITY_MIN, le=FORMALITY_MAX)
    colors: Optional[list[Color]] = Field(default=None, min_length=MIN_COLORS, max_length=MAX_COLORS)

    @model_validator(mode="after")
    def _not_empty(self):
        if all(v is None for v in self.model_dump().values()):
            raise ValueError("patch must change at least one field")
        return self


class RecommendRequest(Strict):
    """POST /recommend  (the Make outfits button; Next outfit = offset + limit)"""
    anchor_id: ObjectId = Field(pattern=ID_PATTERN)
    limit: int = Field(default=3, ge=1, le=RECOMMEND_MAX_LIMIT)
    offset: int = Field(default=0, ge=0)
    include_catalog: bool = True


class RecommendResponse(Strict):
    anchor_id: ObjectId = Field(pattern=ID_PATTERN)
    outfits: list[Outfit]                # ordered by rank; may be empty only if total_candidates == 0
    total_candidates: int = Field(ge=0)
    cache_hit: bool

    @model_validator(mode="after")
    def _ordered(self):
        ranks = [o.rank for o in self.outfits]
        if ranks != sorted(ranks):
            raise ValueError("outfits must be ordered by rank")
        if any(o.anchor_id != self.anchor_id for o in self.outfits):
            raise ValueError("every outfit must use the requested anchor")
        return self


class SwapRequest(Strict):
    """POST /recommend/swap  (replace one piece, keep the rest)"""
    outfit_id: ObjectId = Field(pattern=ID_PATTERN)
    replace_item_id: ObjectId = Field(pattern=ID_PATTERN)


class SwapResponse(Strict):
    outfit: Outfit


class RenderRequest(Strict):
    """POST /render  (dressed avatar; the same PNG is the Save look download)"""
    avatar_id: ObjectId = Field(pattern=ID_PATTERN)
    outfit_id: ObjectId = Field(pattern=ID_PATTERN)


class RenderResponse(Strict):
    render: Render


class DeletedCounts(Strict):
    avatars: int = Field(ge=0)
    garments: int = Field(ge=0)
    outfits: int = Field(ge=0)
    renders: int = Field(ge=0)


class DemoResetResponse(Strict):
    """POST /demo/reset  (removes guest avatars and garments and everything derived from them)"""
    deleted: DeletedCounts


# ---------------------------------------------------------------- endpoint registry
# (method, path, request model or multipart/None, success response model or None for 204)
# The S1 scaffold serves every entry from contract/fixtures/api/; check_contract.py
# verifies each has example fixtures.

ENDPOINTS = [
    ("GET",    "/health",                        None,            HealthResponse),
    ("POST",   "/avatar",                        "multipart",     AvatarCreateResponse),
    ("POST",   "/ingest",                        "multipart",     IngestResponse),
    ("POST",   "/ingest/{photo_id}/select",      SelectRequest,   SelectResponse),
    ("GET",    "/garments",                      None,            GarmentListResponse),
    ("PATCH",  "/garments/{garment_id}",         GarmentPatch,    Garment),
    ("DELETE", "/garments/{garment_id}",         None,            None),
    ("POST",   "/recommend",                     RecommendRequest, RecommendResponse),
    ("POST",   "/recommend/swap",                SwapRequest,     SwapResponse),
    ("POST",   "/render",                        RenderRequest,   RenderResponse),
    ("POST",   "/demo/reset",                    None,            DemoResetResponse),
]


def fixture_name(method: str, path: str) -> str:
    """'POST', '/ingest/{photo_id}/select' -> 'post_ingest_select'"""
    parts = [p for p in path.strip("/").split("/") if not p.startswith("{")]
    return "_".join([method.lower(), *parts])
