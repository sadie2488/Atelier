"""Lane B routes. Stub: serves fixtures until B1–B4 replace them."""
from app.routes_scaffold import endpoints_for, fixture_router

LANE_B_PATHS = {"/recommend", "/recommend/swap", "/render"}

router = fixture_router(endpoints_for(LANE_B_PATHS))
