"""
Parameter sweeps over the lifetime solver.

Any of the sweepable inputs can be the x-axis of a 1-D sweep or one of the
two axes of a 2-D grid. Each point is a full lifetime run; the result per
point is the trio the UI plots: exhausted hours, first-condensation hours,
hours per gram.

Sweeps that only move desiccant mass, time constant, desorption or the
full-fraction share one set of hour tables (those inputs do not touch the
weather-driven physics), which makes a grams sweep almost free.

SI in the engine; the API converts the axis values to the user's units.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from engine.geometry import CavityGeometry
from engine.lifetime import LifetimeInputs, LifetimeResult, build_tables, run_lifetime

#: Inputs that can be swept, with a short label and whether changing them
#: invalidates the precomputed hour tables.
SWEEPABLE: dict[str, dict] = {
    "desiccant_grams": {"label": "Desiccant mass", "unit": "g", "tables": False},
    "al_out": {"label": "Existing-window air leakage", "unit": "cfm/ft2 @75Pa", "tables": True},
    "al_in": {"label": "Retrofit air leakage", "unit": "cfm/ft2 @75Pa", "tables": True},
    "dp_pa": {"label": "Operating pressure", "unit": "Pa", "tables": True},
    "ach_out": {"label": "Outdoor leakage (raw)", "unit": "ACH", "tables": True},
    "ach_in": {"label": "Room-side vent (raw)", "unit": "ACH", "tables": True},
    "rh_room": {"label": "Room RH", "unit": "fraction", "tables": True},
    "t_room_c": {"label": "Room temperature", "unit": "degC", "tables": True},
    "width_m": {"label": "Cavity width", "unit": "m", "tables": True},
    "height_m": {"label": "Cavity height", "unit": "m", "tables": True},
    "offset_m": {"label": "Cavity offset", "unit": "m", "tables": True},
    "tau_hours": {"label": "Desiccant time constant", "unit": "h", "tables": False},
}

_GEOMETRY_KEYS = {"width_m", "height_m", "offset_m"}


def _with(inp: LifetimeInputs, key: str, value: float) -> LifetimeInputs:
    """A copy of ``inp`` with one input replaced."""
    if key not in SWEEPABLE:
        raise ValueError(f"{key!r} is not sweepable; choose from {sorted(SWEEPABLE)}")
    if key in _GEOMETRY_KEYS:
        g = inp.geometry
        geo = CavityGeometry(
            width_m=value if key == "width_m" else g.width_m,
            height_m=value if key == "height_m" else g.height_m,
            offset_m=value if key == "offset_m" else g.offset_m,
        )
        return replace(inp, geometry=geo)
    if key == "ach_out":
        return replace(inp, ach_out=value, al_out=None)
    if key == "ach_in":
        return replace(inp, ach_in=value, al_in=None)
    return replace(inp, **{key: value})


@dataclass
class SweepPoint:
    x: float
    y: float | None
    exhausted_hour: int | None
    first_condensation_hour: int | None
    hours_per_gram: float | None
    total_water_g: float
    years_run: int


def sweep_1d(
    inp: LifetimeInputs,
    weather,
    key: str,
    values: list[float],
    poa_w_m2: list[float] | None = None,
) -> list[SweepPoint]:
    """One run per value of ``key``."""
    if not values:
        raise ValueError("values is empty")
    if key not in SWEEPABLE:
        raise ValueError(f"{key!r} is not sweepable; choose from {sorted(SWEEPABLE)}")
    shared = None
    if not SWEEPABLE[key]["tables"]:
        shared = build_tables(inp, weather, poa_w_m2)
    out: list[SweepPoint] = []
    for v in values:
        r = _run(_with(inp, key, v), weather, poa_w_m2, shared)
        out.append(_point(v, None, r))
    return out


def sweep_2d(
    inp: LifetimeInputs,
    weather,
    key_x: str,
    values_x: list[float],
    key_y: str,
    values_y: list[float],
    poa_w_m2: list[float] | None = None,
) -> list[list[SweepPoint]]:
    """Grid indexed [iy][ix]. Tables are rebuilt only when an axis that
    touches them changes, and only along the outer loop."""
    for k in (key_x, key_y):
        if k not in SWEEPABLE:
            raise ValueError(f"{k!r} is not sweepable; choose from {sorted(SWEEPABLE)}")
    if key_x == key_y:
        raise ValueError("key_x and key_y must differ")
    if not values_x or not values_y:
        raise ValueError("axis values are empty")
    x_tables = SWEEPABLE[key_x]["tables"]
    y_tables = SWEEPABLE[key_y]["tables"]
    grid: list[list[SweepPoint]] = []
    for vy in values_y:
        row_inp = _with(inp, key_y, vy)
        shared = None if x_tables else build_tables(row_inp, weather, poa_w_m2)
        row: list[SweepPoint] = []
        for vx in values_x:
            r = _run(_with(row_inp, key_x, vx), weather, poa_w_m2, shared)
            row.append(_point(vx, vy, r))
        grid.append(row)
    return grid


def _run(inp, weather, poa, tables) -> LifetimeResult:
    return run_lifetime(inp, weather, poa, tables=tables, keep_year1=False, keep_daily=False)


def _point(x, y, r: LifetimeResult) -> SweepPoint:
    return SweepPoint(
        x=x, y=y, exhausted_hour=r.exhausted_hour,
        first_condensation_hour=r.first_condensation_hour,
        hours_per_gram=r.hours_per_gram, total_water_g=r.total_water_into_desiccant_g,
        years_run=r.years_run,
    )
