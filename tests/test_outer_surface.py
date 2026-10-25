"""Oct 25 2026 fixes: (1) sun and sky reach the cavity face through the
existing glass, not in full; (2) the 2 m weather wind is converted to the
10 m station wind the formulas assume.

Sources: [PHYSICS] series resistance chain, centre of glass, f at NFRC
         [NSRDB]   wind speed at 2 m since PSM v3 (NSRDB webinar Q&A, Oct 2020)
         [ASHRAE]  power-law wind profile, open-terrain exponent 0.14
"""

from __future__ import annotations

import math

import pytest

import engine.lifetime as L
from engine.cavity import (
    R_EXISTING_LAYER,
    R_OUT_FILM_NFRC,
    exterior_film_coefficient,
    outer_heat_response,
    outer_surface_f,
    radiative_surface_drop,
    sky_longwave_loss_w_m2,
    t_from_f,
)
from engine.geometry import CavityGeometry
from engine.lifetime import LifetimeInputs, build_tables
from engine.pressure import HvacSchedule, wind_dp_pa
from engine.psychro import f_to_c
from engine.weather import WeatherYear

T_ROOM_C = f_to_c(70.0)


# ---------------------------------------------------------------------------
# outer_heat_response: hand calculations and limits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("f, glass, ratio", [
    (0.014, "single", 0.945),     # single pane + VIG
    (0.068, "single", 0.771),     # single pane + SWR
    (0.064, "double", 0.904),     # double pane + VIG
    (0.301, "double", 0.600),     # double pane + SWR
])
def test_cavity_face_share_matches_hand_calc(f, glass, ratio):
    """Calm air, h_out 5.7. Old engine: dT_face = q / h_out (ratio 1)."""
    r = R_EXISTING_LAYER[glass]
    r_out = R_OUT_FILM_NFRC + r
    r_rest = r_out * (1 - f) / f
    hand = r_rest / (5.7 * (r + r_rest) + 1.0)
    _, k_face = outer_heat_response(f, r, 5.7)
    assert k_face == pytest.approx(hand, rel=1e-12)
    assert k_face * 5.7 == pytest.approx(ratio, abs=0.001)


def test_limits_reproduce_the_old_engine_and_the_room():
    # f = 0: the pane is pinned to outdoors, exactly the old q / h_out.
    assert outer_heat_response(0.0, 0.212, 13.3) == (1 / 13.3, 1 / 13.3)
    # f = 1: the cavity face is pinned to the room and cannot move.
    assert outer_heat_response(1.0, 0.006, 13.3)[1] == 0.0


@pytest.mark.parametrize("f", [0.01, 0.05, 0.2, 0.5, 0.9])
@pytest.mark.parametrize("glass", ["single", "double"])
@pytest.mark.parametrize("h", [5.7, 13.3, 30.0])
def test_face_never_moves_more_than_the_surface_or_the_old_formula(f, glass, h):
    k_s, k_f = outer_heat_response(f, R_EXISTING_LAYER[glass], h)
    assert 0.0 < k_f <= k_s <= 1.0 / h


def test_more_wind_less_response():
    assert outer_heat_response(0.2, 0.212, 30.0)[1] < outer_heat_response(0.2, 0.212, 5.7)[1]


def test_outer_surface_f():
    assert outer_surface_f(0.301, 0.212) == pytest.approx(0.301 * R_OUT_FILM_NFRC / (R_OUT_FILM_NFRC + 0.212))
    assert outer_surface_f(0.301, 0.212) < 0.301
    assert outer_surface_f(0.0, 0.212) == 0.0


def test_radiative_drop_unchanged_by_refactor():
    q = sky_longwave_loss_w_m2(0.0, 0.0, opacity=0.0)
    assert radiative_surface_drop(0.0, 0.0, 5.7) == pytest.approx(-q / 5.7)
    # Hand calc: Swinbank sky at 0 degC is 0.0552 x 273.15^1.5 = 249.19 K;
    # q = 0.84 x 5.670e-8 x 0.5 x (5.5668e9 - 3.8559e9) = 40.7 W/m2
    assert q == pytest.approx(40.7, abs=0.1)


# ---------------------------------------------------------------------------
# In the solver
# ---------------------------------------------------------------------------

def _year(n=48, t=-5.0, wind=3.0, wdir=0.0, cloud=0.0):
    return WeatherYear(t_out_c=[t] * n, rh_out=[0.8] * n, wind_m_s=[wind] * n,
                       wind_dir_deg=[wdir] * n, cloud_type=[cloud] * n)


def _inp(f=0.301, glass="double", sky=True, absorptance=0.0, **kw):
    g = CavityGeometry.from_inches(width_in=60, height_in=96, offset_in=0.6)
    base = dict(geometry=g, f_cold=f, f_warm=min(0.99, f + 0.2), u_assembly=1.4,
                t_room_c=T_ROOM_C, rh_room=0.3, al_out=0.005, al_in=0.005,
                hvac=HvacSchedule(occupied_pa=0.0, unoccupied_pa=0.0),
                building_floors=1, window_floor=1, facade_azimuth_deg=0.0,
                desiccant_grams=0.0, sky_radiation=sky, absorptance=absorptance,
                pane_coupling=False, existing_glass=glass, max_years=1)
    base.update(kw)
    return LifetimeInputs(**base)


def test_solver_sky_drop_is_the_new_share():
    """Clear sky, no sun, no vent warming: the cavity face drops by
    q_sky(T_outer) x k_face, with the outer surface at f_outer."""
    w = _year()
    inp = _inp()
    tb = build_tables(inp, w, None)
    h = exterior_film_coefficient(3.0 * L.WIND_STATION_FACTOR)
    k_s, k_f = outer_heat_response(0.301, 0.212, h)
    t_outer = t_from_f(outer_surface_f(0.301, 0.212), -5.0, T_ROOM_C)
    expect = t_from_f(0.301, -5.0, T_ROOM_C) - sky_longwave_loss_w_m2(t_outer, -5.0) * k_f
    assert tb.t_cold_c[0] == pytest.approx(expect, abs=1e-9)


@pytest.mark.parametrize("f, glass", [(0.014, "single"), (0.068, "single"), (0.064, "double"), (0.301, "double")])
def test_fix_never_cools_the_face_more_than_before(f, glass):
    """The old engine applied q / h_out at the cavity-face temperature. The
    new drop is never larger: a smaller share, at a colder surface."""
    w = _year()
    tb = build_tables(_inp(f=f, glass=glass), w, None)
    h = exterior_film_coefficient(3.0 * L.WIND_STATION_FACTOR)
    t0 = t_from_f(f, -5.0, T_ROOM_C)
    old = t0 + radiative_surface_drop(t0, -5.0, h)
    assert tb.t_cold_c[0] >= old - 1e-12


def test_fix_never_warms_the_face_more_than_before_in_sun():
    w = _year()
    poa = [600.0] * 48
    tb = build_tables(_inp(sky=False, absorptance=0.1), w, poa)
    h = exterior_film_coefficient(3.0 * L.WIND_STATION_FACTOR)
    old = t_from_f(0.301, -5.0, T_ROOM_C) + 0.1 * 600.0 / h
    new_rise = tb.t_cold_c[0] - t_from_f(0.301, -5.0, T_ROOM_C)
    assert 0.0 < new_rise < old - t_from_f(0.301, -5.0, T_ROOM_C)


def test_existing_glass_is_validated():
    with pytest.raises(ValueError):
        _inp(glass="triple")


# ---------------------------------------------------------------------------
# Wind: 2 m weather -> 10 m station
# ---------------------------------------------------------------------------

def test_wind_station_factor():
    assert L.WIND_STATION_FACTOR == pytest.approx(5.0 ** 0.14)
    assert L.WIND_STATION_FACTOR == pytest.approx(1.2527, abs=1e-4)


def test_wind_pressure_uses_the_10m_wind():
    """North facade, wind from the north (Cp +0.6), no HVAC, window at the
    neutral plane (1 floor, floor 1): dP is the wind term alone, at
    v10 = 1.2527 x v2."""
    w = _year(wind=4.0, wdir=0.0)
    tb = build_tables(_inp(sky=False), w, None)
    assert tb.dp_pa[0] == pytest.approx(wind_dp_pa(4.0 * L.WIND_STATION_FACTOR, 0.0, 0.0), rel=1e-12)
    assert tb.dp_pa[0] == pytest.approx(-0.5 * 1.2 * (4.0 * 1.2527) ** 2 * 0.6, rel=1e-4)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_api_existing_glass(monkeypatch):
    import gzip
    import os
    from pathlib import Path
    from engine.weather import Location, parse_nsrdb_csv
    os.environ.setdefault("MAPBOX_TOKEN", "pk.test")
    os.environ.setdefault("NREL_API_KEY", "test")
    import app as flask_app
    year = parse_nsrdb_csv(gzip.open(Path(__file__).parent / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz", "rt").read())
    loc = Location("x", "277 PARK AVE, NEW YORK, NY 10172", 40.7568, -73.9742)
    monkeypatch.setattr(flask_app, "get_weather_for_address", lambda *a, **k: (loc, year, False))
    c = flask_app.app.test_client()
    q = "/api/lifetime?grams=0&max_years=1&trace=0&f_cold=0.301&u_ip=0.249"
    assert c.get(q).get_json()["inputs"]["existing_glass"] == "single"
    assert c.get(q + "&existing_glass=double").get_json()["inputs"]["existing_glass"] == "double"
    assert c.get(q + "&existing_glass=triple").status_code == 400
    p = c.get("/api/presets").get_json()
    assert p["defaults"]["existing_glass"] == "single"
    assert {e["key"] for e in p["existing_glass"]} == {"single", "double"}
