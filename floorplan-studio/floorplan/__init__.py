"""floorplan-studio: generate residential floor plans from a footprint and a room program.

Nothing here depends on anything outside the Python standard library.

    from floorplan.geometry import Polygon
    from floorplan.spec import PlanSpec
    from floorplan.layout import generate

    spec = PlanSpec.from_program(Polygon.rectangle(48, 32), bedrooms=3, bathrooms=2)
    best = generate(spec, variants=3)[0]
"""

from .geometry import Polygon, Rect
from .layout import generate, layout_once
from .plan import Opening, PlacedRoom, Plan
from .spec import CATALOG, PlanSpec, RoomSpec

__all__ = [
    "CATALOG", "Opening", "PlacedRoom", "Plan", "PlanSpec", "Polygon", "Rect",
    "RoomSpec", "generate", "layout_once",
]
__version__ = "0.1.0.dev0"
