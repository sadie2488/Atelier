"""Lane A routes. Serves fixtures until A-tasks replace them."""
from contract.schemas import ENDPOINTS

from app.routes_b import LANE_B_PATHS
from app.routes_scaffold import endpoints_for, fixture_router

LANE_A_PATHS = {e[1] for e in ENDPOINTS} - LANE_B_PATHS

router = fixture_router(endpoints_for(LANE_A_PATHS))
