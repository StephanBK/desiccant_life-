"""
INOVUES - Desiccant Lifetime Simulator
Flask application entry point.

Doc ID: ANLY-003

ENDPOINTS
    GET /api/presets           ladders, desiccant library, sweepable inputs
    GET /api/lifetime          one full run: headline numbers, per-year table,
                               daily trace, year-1 hourly trace, hour tables
    GET /api/sweep             1-D (key, values) or 2-D (key_x, key_y, ...)
    GET /api/export.xlsx       the /api/lifetime run as a workbook
    GET /                      the React build in static/dist

UNITS AT THE BOUNDARY
    Inches, degF, Btu/hr.ft2.degF and grams in; everything inside the engine
    is SI. Conversion happens once, here.
"""

from __future__ import annotations

import os
from dataclasses import asdict, replace

from flask import Flask, Response, jsonify, request, send_from_directory

from engine import psychro
from engine.cavity import f_warm_estimate
from engine.desiccant import DESICCANTS, DEFAULT_DESICCANT, cartridge_volume_ml
from engine.geometry import CavityGeometry
from engine.leakage import (
    DEFAULT_BEAD_DEPTH_M, DEFAULT_BEAD_WIDTH_M, DEFAULT_OPERATING_PA, DEFAULT_SEALANT, EXISTING_BY_KEY,
    EXISTING_PRESETS, RETROFIT_BY_KEY, RETROFIT_PRESETS, SEALANTS, air_leakage_from_ach,
    sealant_diffusion_kg_per_h,
)
from engine.lifetime import FOG_LEVELS, LifetimeInputs, LifetimeResult, run_lifetime
from engine.report import workbook_bytes
from engine.pressure import (
    CP_TABLE, DEFAULT_FLOOR_HEIGHT_M, DEFAULT_FLOORS, DEFAULT_LOOP_EXPONENT, DEFAULT_LOOP_K,
    DEFAULT_OCC_END_H, DEFAULT_OCC_START_H,
    DEFAULT_P_OCCUPIED_PA, DEFAULT_P_UNOCCUPIED_PA, DEFAULT_WINDOW_FLOOR, HvacSchedule,
)
from engine.solar import ORIENTATIONS, poa_series
from engine.sweep import SWEEPABLE, sweep_1d, sweep_2d
from engine.weather import WeatherError, get_weather_for_address

APP_VERSION = "0.1.0"
APP_NAME = "INOVUES Desiccant Lifetime Simulator"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "dist")
app = Flask(__name__, static_folder=DIST, static_url_path="")

# First-load scenario (Sep 11 2026): INOVUES practice, existing window
# wet-sealed then a wet-sealed retrofit, both at the E283 detection floor,
# silicone bead diffusion as the vapour floor. See engine/leakage.py.
DEFAULTS = {
    "address": "277 Park Avenue, New York, NY",
    "width_in": 60.0, "height_in": 96.0, "offset_in": 0.6,
    "f_cold": 0.30, "u_ip": 0.30, "r_ip": 0.97,
    "t_in_f": 70.0, "rh_in_pct": 35.0,
    "al_out": "wet_sealed", "al_in": "wet_sealed", "dp_pa": DEFAULT_OPERATING_PA,
    "sealant_out": DEFAULT_SEALANT, "sealant_in": DEFAULT_SEALANT, "bead_width_in": 0.25, "bead_depth_in": 0.25,
    "grams": 1000.0, "desiccant": DEFAULT_DESICCANT,
    "orientation": "south", "absorptance": 0.10,
    # Signed pressure model (engine.pressure): HVAC schedule, stack from
    # floor position, wind by direction against the facade.
    "p_occ_pa": DEFAULT_P_OCCUPIED_PA, "p_unocc_pa": DEFAULT_P_UNOCCUPIED_PA,
    "occ_start_h": DEFAULT_OCC_START_H, "occ_end_h": DEFAULT_OCC_END_H, "weekdays_only": True,
    "floors": DEFAULT_FLOORS, "window_floor": DEFAULT_WINDOW_FLOOR, "floor_height_ft": round(DEFAULT_FLOOR_HEIGHT_M / 0.3048, 2),
    "series_model": True, "breathing": True,
    "loops": True, "loop_k": DEFAULT_LOOP_K, "loop_n": DEFAULT_LOOP_EXPONENT,
}


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

class BadRequest(ValueError):
    """A user-correctable problem with the query string."""


def _float(name, default=None, minimum=None, maximum=None) -> float:
    raw = request.args.get(name)
    if raw is None or raw == "":
        if default is None:
            raise BadRequest(f"Missing required parameter {name!r}")
        return default
    try:
        value = float(raw)
    except ValueError:
        raise BadRequest(f"Parameter {name!r} must be a number, got {raw!r}")
    if minimum is not None and value < minimum:
        raise BadRequest(f"Parameter {name!r} must be at least {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise BadRequest(f"Parameter {name!r} must be at most {maximum}, got {value}")
    return value


def _int(name, default, minimum, maximum) -> int:
    return int(_float(name, default=float(default), minimum=minimum, maximum=maximum))


def _bool(name: str, default: bool) -> bool:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _ach(name: str, presets: dict, default: str) -> float:
    raw = (request.args.get(name) or default).strip().lower()
    if raw in presets:
        return presets[raw]
    try:
        value = float(raw)
    except ValueError:
        raise BadRequest(f"Parameter {name!r} must be a number or one of {sorted(presets)}, got {raw!r}")
    if value < 0:
        raise BadRequest(f"Parameter {name!r} cannot be negative")
    return value


def _leak(name: str, by_key: dict, default: str) -> float:
    """Rated air leakage, cfm/ft2 at 75 Pa: a preset key or a number."""
    raw = (request.args.get(name) or default).strip().lower()
    if raw in by_key:
        return by_key[raw].al_cfm_ft2
    try:
        value = float(raw)
    except ValueError:
        raise BadRequest(f"Parameter {name!r} must be a number or one of {sorted(by_key)}, got {raw!r}")
    if value < 0:
        raise BadRequest(f"Parameter {name!r} cannot be negative")
    return value


def _choice(name: str, options: dict, default: str) -> str:
    raw = (request.args.get(name) or default).strip().lower()
    if raw not in options:
        raise BadRequest(f"Parameter {name!r} must be one of {sorted(options)}, got {raw!r}")
    return raw


def _parse_inputs() -> tuple[LifetimeInputs, dict]:
    """Query string -> LifetimeInputs (SI). Returns the echo dict too."""
    address = (request.args.get("address") or DEFAULTS["address"]).strip()
    try:
        geometry = CavityGeometry.from_inches(
            width_in=_float("width_in", DEFAULTS["width_in"], 1.0, 400.0),
            height_in=_float("height_in", DEFAULTS["height_in"], 1.0, 400.0),
            offset_in=_float("offset_in", DEFAULTS["offset_in"], 0.05, 12.0),
        )
    except ValueError as exc:
        raise BadRequest(str(exc))

    f_cold = _float("f_cold", DEFAULTS["f_cold"], 0.0, 1.0)
    u_si = psychro.u_ip_to_si(_float("u_ip", DEFAULTS["u_ip"], 0.01, 2.0))
    r_si = psychro.r_ip_to_si(_float("r_ip", DEFAULTS["r_ip"], 0.01, 100.0))
    raw_fw = request.args.get("f_warm")
    if raw_fw:
        f_warm = _float("f_warm", minimum=0.0, maximum=1.0)
    else:
        try:
            f_warm = f_warm_estimate(f_cold, r_si, u_si)
        except ValueError as exc:
            raise BadRequest(str(exc))

    desiccant = (request.args.get("desiccant") or DEFAULTS["desiccant"]).strip().lower()
    if desiccant not in DESICCANTS:
        raise BadRequest(f"Unknown desiccant {desiccant!r}; choose from {sorted(DESICCANTS)}")
    orientation = (request.args.get("orientation") or DEFAULTS["orientation"]).strip().lower()
    if orientation not in ORIENTATIONS:
        raise BadRequest(f"orientation must be one of {sorted(ORIENTATIONS)}")
    raw_tau = request.args.get("tau_h")

    try:
        hvac = HvacSchedule(
            occupied_pa=_float("p_occ_pa", DEFAULTS["p_occ_pa"], -75.0, 75.0),
            unoccupied_pa=_float("p_unocc_pa", DEFAULTS["p_unocc_pa"], -75.0, 75.0),
            start_h=_int("occ_start_h", DEFAULTS["occ_start_h"], 0, 24),
            end_h=_int("occ_end_h", DEFAULTS["occ_end_h"], 0, 24),
            weekdays_only=_bool("weekdays_only", DEFAULTS["weekdays_only"]),
        )
        inp = LifetimeInputs(
            geometry=geometry, f_cold=f_cold, f_warm=f_warm, u_assembly=u_si,
            t_room_c=psychro.f_to_c(_float("t_in", DEFAULTS["t_in_f"], 40.0, 100.0)),
            rh_room=_float("rh_in", DEFAULTS["rh_in_pct"], 0.0, 100.0) / 100.0,
            # Raw ACH is an advanced override; the normal path is rated leakage.
            al_out=None if request.args.get("ach_out") else _leak("al_out", EXISTING_BY_KEY, DEFAULTS["al_out"]),
            al_in=None if request.args.get("ach_in") else _leak("al_in", RETROFIT_BY_KEY, DEFAULTS["al_in"]),
            ach_out=_ach("ach_out", {}, "0") if request.args.get("ach_out") else 0.0,
            ach_in=_ach("ach_in", {}, "0") if request.args.get("ach_in") else 0.0,
            dp_pa=_float("dp_pa", DEFAULTS["dp_pa"], 0.0, 75.0),
            series_model=_bool("series_model", DEFAULTS["series_model"]),
            breathing=_bool("breathing", DEFAULTS["breathing"]),
            loops=_bool("loops", DEFAULTS["loops"]),
            loop_k=_float("loop_k", DEFAULTS["loop_k"], 0.0, 1.0),
            loop_exponent=_float("loop_n", DEFAULTS["loop_n"], 0.5, 1.0),
            hvac=hvac,
            building_floors=_int("floors", DEFAULTS["floors"], 1, 200),
            window_floor=_int("window_floor", DEFAULTS["window_floor"], 1, 200),
            floor_height_m=_float("floor_height_ft", DEFAULTS["floor_height_ft"], 6.0, 30.0) * 0.3048,
            facade_azimuth_deg=ORIENTATIONS[orientation],
            sealant_out=_choice("sealant_out", SEALANTS, DEFAULTS["sealant_out"]),
            sealant_in=_choice("sealant_in", SEALANTS, DEFAULTS["sealant_in"]),
            bead_width_m=_float("bead_width_in", DEFAULTS["bead_width_in"], 0.0, 2.0) * 0.0254,
            bead_depth_m=_float("bead_depth_in", DEFAULTS["bead_depth_in"], 0.02, 2.0) * 0.0254,
            wind_scaling=_bool("wind_scaling", True),
            desiccant_grams=_float("grams", DEFAULTS["grams"], 0.0, 100000.0),
            desiccant_key=desiccant,
            tau_hours=_float("tau_h", minimum=0.01, maximum=1000.0) if raw_tau else None,
            allow_desorption=_bool("desorption", False),
            full_fraction=_float("full_fraction", 0.95, 0.5, 1.0),
            pane_coupling=_bool("pane_coupling", True),
            absorptance=_float("absorptance", DEFAULTS["absorptance"], 0.0, 1.0),
            sky_radiation=_bool("sky_radiation", True),
            max_years=_int("max_years", 20, 1, 50),
            substeps=_int("substeps", 4, 1, 24),
            visible_film_kg=_float("visible_um", 5.0, 0.0, 1000.0) / 1000.0,
        )
    except ValueError as exc:
        raise BadRequest(str(exc))

    echo = {
        "address": address, "orientation": orientation,
        "width_in": geometry.width_in, "height_in": geometry.height_in, "offset_in": geometry.offset_in,
        "f_cold": f_cold, "f_warm": round(f_warm, 4),
        "u_ip": round(psychro.u_si_to_ip(u_si), 4), "r_ip": round(psychro.r_si_to_ip(r_si), 4),
        "t_in_f": round(psychro.c_to_f(inp.t_room_c), 2), "rh_in_pct": inp.rh_room * 100.0,
        "al_out": inp.al_out, "al_in": inp.al_in, "dp_pa": inp.dp_pa,
        "ach_out": round(inp.ach_out, 4), "ach_in": round(inp.ach_in, 4), "wind_scaling": inp.wind_scaling,
        "series_model": inp.uses_series_model, "breathing": inp.breathing,
        "loops": inp.loops, "loop_k": inp.loop_k, "loop_n": inp.loop_exponent,
        "p_occ_pa": hvac.occupied_pa, "p_unocc_pa": hvac.unoccupied_pa,
        "occ_start_h": hvac.start_h, "occ_end_h": hvac.end_h, "weekdays_only": hvac.weekdays_only,
        "floors": inp.building_floors, "window_floor": inp.window_floor,
        "floor_height_ft": round(inp.floor_height_m / 0.3048, 2),
        "height_above_npl_ft": round(inp.height_above_npl_m / 0.3048, 1),
        "facade_azimuth_deg": inp.facade_azimuth_deg,
        "sealant_out": inp.sealant_out, "sealant_in": inp.sealant_in,
        "bead_width_in": round(inp.bead_width_m / 0.0254, 3), "bead_depth_in": round(inp.bead_depth_m / 0.0254, 3),
        "diffusion_g_per_day": round(24 * 1000 * (
            sealant_diffusion_kg_per_h(geometry.perimeter_m, inp.bead_width_m, inp.bead_depth_m, SEALANTS[inp.sealant_in],
                                       psychro.p_w_from_w(psychro.w_from_t_rh(inp.t_room_c, inp.rh_room)))), 4),
        "grams": inp.desiccant_grams, "desiccant": desiccant, "tau_h": inp.tau,
        "desorption": inp.allow_desorption, "full_fraction": inp.full_fraction,
        "pane_coupling": inp.pane_coupling, "absorptance": inp.absorptance,
        "sky_radiation": inp.sky_radiation, "max_years": inp.max_years,
        "cartridge_ml": round(cartridge_volume_ml(inp.desiccant_grams, inp.desiccant), 1),
        "capacity_g": round(inp.desiccant_grams * inp.desiccant.q_max(25.0), 2),
    }
    return inp, echo


def _weather(address: str, orientation: str):
    location, weather, cached = get_weather_for_address(address)
    poa = None
    if weather.has_solar:
        poa = poa_series(
            weather.ghi_w_m2, weather.dni_w_m2, weather.dhi_w_m2,
            weather.grid_lat, weather.grid_lon, weather.time_zone or 0.0,
            ORIENTATIONS[orientation],
        )
    return location, weather, cached, poa


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _round_list(xs, nd=4):
    return [round(x, nd) for x in xs]


def _headline(r: LifetimeResult) -> dict:
    ex = r.exhausted_hour
    fc = r.first_condensation_hour
    return {
        "exhausted_hour": ex,
        "exhausted_days": None if ex is None else round(ex / 24.0, 1),
        "exhausted_years": None if ex is None else round(ex / 8760.0, 3),
        "first_condensation_hour": fc,
        "first_condensation_days": None if fc is None else round(fc / 24.0, 1),
        # Film above the visible threshold (visible_um), not just any liquid.
        "first_visible_hour": r.first_visible_hour,
        "first_visible_days": None if r.first_visible_hour is None else round(r.first_visible_hour / 24.0, 1),
        "hours_per_gram": None if r.hours_per_gram is None else round(r.hours_per_gram, 2),
        "years_run": r.years_run,
        "hours_run": r.hours_run,
        "capped": ex is None and r.years_run >= r.inputs.max_years,
        "final_loading": round(r.final_loading, 4),
        "final_loading_pct_of_max": round(100.0 * r.final_loading / r.inputs.desiccant.q_max(25.0), 1),
        "final_rh_eq_pct": round(100.0 * r.final_rh_eq, 2),
        "total_water_into_desiccant_g": round(r.total_water_into_desiccant_g, 2),
    }


def _round_dict(d: dict, nd: int = 2) -> dict:
    return {k: (None if v is None else round(v, nd)) for k, v in d.items()}


def _result_payload(r: LifetimeResult, echo: dict, location, weather, cached: bool, trace: bool) -> dict:
    tb = r.tables
    payload = {
        "app": APP_NAME, "version": APP_VERSION,
        "inputs": echo,
        "location": location.__dict__ if hasattr(location, "__dict__") else str(location),
        "weather": {**weather.describe(), "cached": cached},
        "headline": _headline(r),
        "pressure": _pressure_summary(tb, weather),
        # Net water by source. "life": up to the hour the sieve is full (the
        # headline split); "run": the whole simulation incl. aftermath.
        # Shares are signed and sum to 100; a negative share is a path that
        # REMOVED water (its air was drier than the cavity). None when the
        # net total is not positive.
        "contributions": {
            "life": _round_dict(r.contributions()),
            "run": _round_dict(r.contributions_run()),
            "life_hours": r.exhausted_hour if r.exhausted_hour is not None else r.hours_run,
        },
        "years": [asdict(y) for y in r.years],
        "daily": {
            "loading": _round_list(r.daily_loading, 5),
            "rh_eq_pct": _round_list([x * 100 for x in r.daily_rh_eq], 3),
            "cavity_dew_f": _round_list([psychro.c_to_f(x) for x in r.daily_cav_dew_c], 2),
            "pane_min_f": _round_list([psychro.c_to_f(x) for x in r.daily_pane_min_c], 2),
            "film_um": _round_list([x * 1000.0 for x in r.daily_film_max_kg], 3),
            "t_out_f": _round_list([psychro.c_to_f(x) for x in r.daily_t_out_c], 1),
            "rh_out_pct": _round_list([100 * x for x in r.daily_rh_out], 1),
            "condensed_g": _round_list(r.daily_cond_g, 4),
        },
        "q_max_25": r.inputs.desiccant.q_max(25.0),
        "assumptions": ASSUMPTIONS,
    }
    if trace:
        y1 = r.year1
        payload["year1"] = {
            "t_out_f": _round_list([psychro.c_to_f(x) for x in y1["t_out_c"]], 1),
            "t_cold_f": _round_list([psychro.c_to_f(x) for x in y1["t_cold_c"]], 1),
            "t_air_f": _round_list([psychro.c_to_f(x) for x in y1["t_air_c"]], 1),
            "rh_cav_pct": _round_list([x * 100 for x in y1["rh_cav"]], 2),
            "dew_cav_f": _round_list([psychro.c_to_f(x) for x in y1["dew_cav_c"]], 1),
            "film_um": _round_list([x * 1000.0 for x in y1["film_kg"]], 2),
            "loading_pct": _round_list([100.0 * x / r.inputs.desiccant.q_max(25.0) for x in y1["loading"]], 2),
            "rh_eq_pct": _round_list([x * 100 for x in y1["rh_eq"]], 2),
            "uptake_g": _round_list(y1["uptake_g"], 4),
            "condensed_g": _round_list(y1["condensed_g"], 4),
            "ach_out": _round_list(y1["ach_out"], 3),
            "ach_total": _round_list(tb.ach_total, 4),
            "dp_pa": _round_list(tb.dp_pa, 2),
            "loop_out": _round_list(tb.loop_out, 4), "loop_in": _round_list(tb.loop_in, 4),
            "w_supply_gkg": _round_list([x * 1000 for x in tb.w_supply], 3),
            "vent_rise_f": _round_list([x * 1.8 for x in tb.vent_rise_k], 3),
        }
    return payload


def _pressure_summary(tb, weather) -> dict:
    """What the signed pressure model actually did over the year."""
    n = tb.n
    a_tot = tb.ach_total
    mean_ach = sum(a_tot) / n if n else 0.0
    if not tb.dp_pa:
        return {"series_model": False, "mean_ach": round(mean_ach, 4)}
    room = sum(1 for d in tb.dp_pa if d > 0)
    out = sum(1 for d in tb.dp_pa if d < 0)
    lo = sum(tb.loop_out) / n if tb.loop_out else 0.0
    li = sum(tb.loop_in) / n if tb.loop_in else 0.0
    return {
        "series_model": True,
        "mean_ach": round(mean_ach, 4),
        "mean_through_ach": round(max(mean_ach - lo - li, 0.0), 4),
        "mean_loop_out_ach": round(lo, 4), "mean_loop_in_ach": round(li, 4),
        "max_ach": round(max(a_tot), 4),
        "hours_room_fed": room, "hours_outdoor_fed": out, "hours_neutral": n - room - out,
        "mean_abs_dp_pa": round(sum(abs(d) for d in tb.dp_pa) / n, 3),
        "min_dp_pa": round(min(tb.dp_pa), 2), "max_dp_pa": round(max(tb.dp_pa), 2),
        "wind_direction_available": bool(getattr(weather, "wind_dir_deg", None)),
    }


ASSUMPTIONS = [
    "3A isotherm constants are fitted to published vendor curves, not to a supplier sheet.",
    "Desiccant time constant (default 2 h) is an estimate; a vendor can measure it.",
    "Leakage presets: AERC baseline (2.0) and best certified insert (0.06 cfm/ft2) are published; the values between are estimates.",
    "The two layers are in SERIES: one signed room-to-outdoor pressure per hour (HVAC schedule + stack + wind), the same air passes both layers, the tighter layer takes most of the pressure and sets the flow, and the cavity is fed from the high-pressure side only. Crack-flow exponent 0.65.",
    "HVAC pressurisation defaults +5 Pa occupied (weekdays 07 to 19), 0 Pa unoccupied: the low end of the 5 to 25 Pa design range, matching field measurements in existing buildings. ESTIMATE; the value is a parameter.",
    "Stack pressure from the window's height above a mid-height neutral plane (uniform leakage assumed); building height and floor are parameters.",
    "Wind pressure 0.5 rho v^2 Cp with Cp from the wind angle off the facade (+0.6 windward, -0.5 side, -0.3 leeward; ESTIMATE from face-averaged values). Station wind at 10 m, no height or terrain correction. If the weather file lacks wind direction, every windy hour is treated as windward (conservative).",
    "Each layer also has a SINGLE-SIDED buoyant loop through its own cracks (warm air out the high crack, cold air in the low crack, nothing through the other layer): dP_loop = |rho_side - rho_cavity| g k H, flow of half the layer at dP_loop/2. k (fraction of window height between average inlet and outlet) defaults 0.75, ESTIMATE; exponent 0.65 kept below 1 Pa though flow is probably laminar there (n near 1 would give up to 6x less; conservative for life). Gust pumping and the wind-pressure gradient over the face are not modelled.",
    "Thermal breathing (cavity air contracting as it cools, drawing in from both sides in proportion to their leakage) is included; gust pumping (compression by dP/P_atm per gust through one leaky layer) is not, and only matters below about 0.01 ACH.",
    "Wet-sealed preset (0.005 cfm/ft2) is the ASTM E283 detection floor, not a measurement of INOVUES seals; a cavity pressurisation test would replace it.",
    "Sealant vapour diffusion uses ASTM E96 permeability ranges (silicone 30, PIB 0.3 g.mm/m2/day). Each bead is a SIGNED path driven by its own vapour-pressure gradient, room-to-cavity through the retrofit bead and outdoor-to-cavity through the existing window's bead, folded into the same balance as the vents; a bead facing a drier side removes water. The dry-cavity flux (full source vapour pressure against an empty cavity) is the reporting upper bound.",
    "Pane warming from vent air is an upper bound.",
    "Evaporation from the pane is instantaneous up to saturation (upper bound on drying).",
    "Retained film cap 100 um; visible threshold 5 um; both unmeasured.",
    "'Exhausted' = 95 % of 25 degC capacity; at 35 % room RH the sieve equilibrates at 96.7 %, so thresholds above that never fire.",
    "Lifetime: the tighter layer sets the THROUGH-flow, but each layer's own leakage sets its single-sided LOOP with the side it faces, so BOTH seals matter. A hermetic retrofit over an unsealed old window still breathes outdoor air at a few ACH through the old window alone. Once both are airtight the sealant's vapour permeability is the floor.",
    "The two hermetic / wet-sealed presets bracket one unknown: what a field-applied silicone wet seal actually leaks. Weeks at the E283 floor, years at IGU-grade. A cavity pressure-decay test on an installed unit is the measurement that settles it.",
    "TMY year repeated; no climate trend, no year-to-year variation.",
]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.errorhandler(BadRequest)
def _bad_request(exc):
    return jsonify({"error": str(exc)}), 400


@app.errorhandler(WeatherError)
def _weather_error(exc):
    return jsonify({"error": str(exc)}), 502


@app.get("/api/presets")
def presets():
    return jsonify({
        "app": APP_NAME, "version": APP_VERSION,
        "defaults": DEFAULTS,
        "al_out": [asdict(p) for p in EXISTING_PRESETS],
        "al_in": [asdict(p) for p in RETROFIT_PRESETS],
        "sealants": [asdict(v) for v in SEALANTS.values()],
        "leakage_reference": {
            "test_pressure_pa": 75.0, "flow_exponent": 0.65, "default_operating_pa": DEFAULT_OPERATING_PA,
            "cp_table": [{"angle_deg": a, "cp": c} for a, c in CP_TABLE],
            "aerc_url": "https://aercenergyrating.org/product-search/commercial-product-search/",
            "note": "Air leakage in cfm/ft2 at 75 Pa per ASTM E283 / AERC. Cavity ACH = AL x 18.29 x (dP/75)^0.65 / offset.",
        },
        "desiccants": [
            {
                "key": d.key, "name": d.name, "q_max_25": d.q_max_25, "tau_hours": d.tau_hours,
                "bulk_density_kg_m3": d.bulk_density_kg_m3, "source": d.source,
                "isotherm_25c": [{"rh_pct": rh, "q_pct": round(100 * d.q_eq(rh / 100, 25.0), 2)}
                                 for rh in (0, 0.5, 1, 2, 5, 10, 20, 30, 50, 70, 100)],
                "isotherm_60c": [{"rh_pct": rh, "q_pct": round(100 * d.q_eq(rh / 100, 60.0), 2)}
                                 for rh in (0, 0.5, 1, 2, 5, 10, 20, 30, 50, 70, 100)],
            }
            for d in DESICCANTS.values()
        ],
        "sweepable": SWEEPABLE,
        "orientations": list(ORIENTATIONS),
        "assumptions": ASSUMPTIONS,
    })


@app.get("/api/lifetime")
def lifetime():
    inp, echo = _parse_inputs()
    # Opt-in (2026-09-23, 277 Park app): the hourly fog map and whole years
    # simulated after the desiccant fills. Absent = original behaviour.
    fog_map = _bool("fog_map", False)
    years_after_full = _int("years_after_full", 0, 0, 5)
    location, weather, cached, poa = _weather(echo["address"], echo["orientation"])
    r = run_lifetime(inp, weather, poa, keep_year1=True, keep_daily=True,
                     keep_fog=fog_map, years_after_full=years_after_full)
    payload = _result_payload(r, echo, location, weather, cached, trace=_bool("trace", True))
    if fog_map:
        payload["fog"] = {
            # One entry per simulated year: a string of 8,760 digits in
            # hour-of-year order, '0' = clear, '1'..'9' = visible fog
            # intensity, log-spaced from visible_um to max_um; None for a
            # year without a visible hour.
            "years": r.fog_years,
            "levels": FOG_LEVELS,
            "scale": "log",
            "visible_um": round(inp.visible_film_kg * 1000.0, 3),
            "max_um": round(inp.max_film_kg * 1000.0, 3),
            "years_after_full": years_after_full,
        }
    return jsonify(payload)


def _axis(prefix: str) -> tuple[str, list[float]]:
    """key + comma-separated values in USER units -> engine units."""
    key = (request.args.get(f"{prefix}_key") or "").strip()
    raw = (request.args.get(f"{prefix}_values") or "").strip()
    if key not in SWEEPABLE:
        raise BadRequest(f"{prefix}_key must be one of {sorted(SWEEPABLE)}")
    try:
        vals = [float(v) for v in raw.split(",") if v.strip()]
    except ValueError:
        raise BadRequest(f"{prefix}_values must be comma-separated numbers")
    if not vals or len(vals) > 40:
        raise BadRequest(f"{prefix}_values needs 1..40 values")
    conv = {
        "rh_room": lambda v: v / 100.0,
        "t_room_c": lambda v: psychro.f_to_c(v),
        "width_m": lambda v: v * 0.0254,
        "height_m": lambda v: v * 0.0254,
        "offset_m": lambda v: v * 0.0254,
    }.get(key, lambda v: v)
    return key, [conv(v) for v in vals], vals


@app.get("/api/sweep")
def sweep():
    inp, echo = _parse_inputs()
    inp = replace(inp, max_years=min(inp.max_years, _int("sweep_max_years", 5, 1, 20)))
    location, weather, cached, poa = _weather(echo["address"], echo["orientation"])
    kx, vx, ux = _axis("x")
    if request.args.get("y_key"):
        ky, vy, uy = _axis("y")
        if ky == kx:
            raise BadRequest("x_key and y_key must differ")
        if len(vx) * len(vy) > 400:
            raise BadRequest("grid too large; keep x * y <= 400 points")
        grid = sweep_2d(inp, weather, kx, vx, ky, vy, poa)
        rows = [[_sp(p, ux[ix], uy[iy]) for ix, p in enumerate(row)] for iy, row in enumerate(grid)]
        return jsonify({"mode": "2d", "inputs": echo, "x_key": kx, "y_key": ky,
                        "x_values": ux, "y_values": uy, "grid": rows,
                        "sweep_max_years": inp.max_years})
    pts = sweep_1d(inp, weather, kx, vx, poa)
    return jsonify({"mode": "1d", "inputs": echo, "x_key": kx, "x_values": ux,
                    "points": [_sp(p, ux[i], None) for i, p in enumerate(pts)],
                    "sweep_max_years": inp.max_years})


def _sp(p, x_user, y_user) -> dict:
    return {
        "x": x_user, "y": y_user,
        "exhausted_hour": p.exhausted_hour,
        "exhausted_days": None if p.exhausted_hour is None else round(p.exhausted_hour / 24.0, 1),
        "first_condensation_hour": p.first_condensation_hour,
        "first_condensation_days": None if p.first_condensation_hour is None else round(p.first_condensation_hour / 24.0, 1),
        "hours_per_gram": None if p.hours_per_gram is None else round(p.hours_per_gram, 2),
        "total_water_g": round(p.total_water_g, 2),
        "years_run": p.years_run,
    }


@app.get("/api/export.xlsx")
def export_xlsx():
    inp, echo = _parse_inputs()
    location, weather, cached, poa = _weather(echo["address"], echo["orientation"])
    r = run_lifetime(inp, weather, poa, keep_year1=True, keep_daily=True)
    data = workbook_bytes(r, echo, _headline(r), weather.describe(), ASSUMPTIONS)
    name = f"desiccant_life_{int(inp.desiccant_grams)}g.xlsx"
    return Response(data, mimetype=XLSX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "app": APP_NAME, "version": APP_VERSION})


@app.get("/")
def index():
    resp = send_from_directory(DIST, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
