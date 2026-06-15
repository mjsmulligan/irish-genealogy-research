"""
GRA — Pipeline package.

Re-exports the public entry points for each pipeline stage so that
callers can import from src.pipeline directly.

Stage sequence:
    1. ingest          — src.ingest.census.ingest_census
    2. place-resolve   — run_place_resolution
    3. household       — run_household_inference
    4. link            — src.pipeline.linkage (two entry points)
    5. rebuild-consensus — src.pipeline.scoring.rebuild_consensus

Orchestration across stages: src.pipeline.pipeline
"""

from src.pipeline.place_resolution import (
    run_place_resolution,
    print_place_resolution_report,
)
from src.pipeline.household_inference import (
    run_household_inference,
    print_household_inference_report,
)

__all__ = [
    "run_place_resolution",
    "print_place_resolution_report",
    "run_household_inference",
    "print_household_inference_report",
]
