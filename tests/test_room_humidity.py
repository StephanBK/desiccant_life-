"""
Room air modes (engine.room, Oct 19 2026): "fixed" RH as before, or an
"unhumidified" building (outdoor moisture plus the occupants'), and the
stack factor. The guard that matters most: with every new input at its
default nothing moves, and the hourly path, fed a constant, reproduces the
fixed path exactly.
"""

from __future__ import annotations

import gzip
import math
import os
from dataclasses import replace
from pathlib import Path

import pytest

from engine import lifetime as L
from engine import room
from engine.geometry import CavityGeometry
from engine.lifetime import LifetimeInputs, build_tables, run_lifetime
from engine.pressure import HvacSchedule
from engine.psychro import atmospheric_pressure_pa, rh_from_t_w, w_from_t_rh
from engine.weather import Location, parse_nsrdb_csv

FIXTURE = Path(__file__).parent / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz"


@pytest.fixture(scope="module")
def weather():
    return parse_nsrdb_csv(gzip.open(FIXTURE, "rt").read())


def base(**kw) -> LifetimeInputs:
    """Series model, leaky old window under a tight retrofit, VIG-like cold pane."""
    args = dict(
        geometry=CavityGeometry.from_inches(60, 96, 0.6), f_cold=0.064, f_warm=0.59,
        u_assembly=0.78, t_room_c=21.1, rh_room=0.30, al_out=1.0, al_in=0.06,
        desiccant_grams=0.0, absorptance=0.0, sky_radiation=False, max_years=1,
        allow_desorption=True,
        # +5 Pa occupied, the default before 2026-10-25: these tests need a
        # foggy year to test the room-air mechanics, and at today's +2 Pa this
        # setup no longer fogs.
        hvac=HvacSchedule(occupied_pa=5.0),
    )
    args.update(kw)
    return LifetimeInputs(**args)


def fog_hours(r) -> int:
    return sum(sum(1 for c in y if c != "0") for y in r.fog_years if y)


# ---------------------------------------------------------------------------
# The series itself
# ---------------------------------------------------------------------------

def test_people_moisture_scales_with_altitude():
    assert room.people_dw(1.2, 101325.0) == pytest.approx(1.2e-3)
    assert room.people_dw(1.2, 83226.0) == pytest.approx(1.2e-3 * 101325.0 / 83226.0)
    with pytest.raises(ValueError):
        room.people_dw(-0.1, 101325.0)


def test_occupied_value_and_fade_after_hours():
    n = 24 * 7
    t, rh = [0.0] * n, [0.5] * n                       # cold, so no cooling cap
    occ = lambda i: 9 <= i % 24 < 17
    w = room.unhumidified_room_w(t, rh, 21.0, 101325.0, occ, people_gkg=1.2, fade_ach=0.5)
    w_o = room.outdoor_w(0.0, 0.5, 101325.0)
    day = 24 * 3
    assert w[day + 10] == pytest.approx(w_o + 1.2e-3, rel=1e-12)            # occupied
    assert w[day + 17] == pytest.approx(w_o + 1.2e-3 * math.exp(-0.5), rel=1e-12)
    assert w[day + 21] == pytest.approx(w_o + 1.2e-3 * math.exp(-2.5), rel=1e-12)
    # no fade: the occupants' moisture stays around the clock
    w0 = room.unhumidified_room_w(t, rh, 21.0, 101325.0, occ, people_gkg=1.2, fade_ach=0.0)
    assert w0[day + 3] == pytest.approx(w_o + 1.2e-3, rel=1e-12)


def test_no_people_follows_outdoor_air_exactly(weather):
    p = atmospheric_pressure_pa(weather.elevation_m)
    w = room.unhumidified_room_w(weather.t_out_c, weather.rh_out, 21.1, p, lambda i: False, people_gkg=0.0)
    tb = build_tables(base(), weather, None)                # fixed mode: its w_out is the reference
    cold = [i for i in range(weather.hours) if weather.t_out_c[i] <= room.COOLING_ABOVE_C]
    assert len(cold) > 3000
    assert all(w[i] == tb.w_out[i] for i in cold)


def test_cooling_cap_and_ceiling():
    t, rh = [32.0] * 48, [0.9] * 48                         # hot and humid outdoors
    w = room.unhumidified_room_w(t, rh, 21.0, 101325.0, lambda i: True, people_gkg=2.0)
    assert max(rh_from_t_w(21.0, x) for x in w) == pytest.approx(room.COOLING_CAP_RH, abs=1e-9)
    t2 = [12.0] * 48                                        # below 60 F: no cooling cap ...
    w2 = room.unhumidified_room_w(t2, [1.0] * 48, 12.5, 101325.0, lambda i: True, people_gkg=5.0)
    assert max(rh_from_t_w(12.5, x) for x in w2) <= room.ROOM_RH_CEILING + 1e-9   # ... but the ceiling


def test_year_wraps_like_the_repeated_weather_year():
    n = 24 * 10
    t, rh = [0.0] * n, [0.4] * n
    occ = lambda i: i == n - 3                              # one occupied hour, three before New Year
    w = room.unhumidified_room_w(t, rh, 21.0, 101325.0, occ, people_gkg=1.0, fade_ach=0.5)
    w_o = room.outdoor_w(0.0, 0.4, 101325.0)
    assert w[0] - w_o == pytest.approx((w[n - 1] - w_o) * math.exp(-0.5), rel=1e-9)


def test_bad_series_inputs_rejected():
    with pytest.raises(ValueError):
        room.unhumidified_room_w([], [], 21.0, 101325.0, lambda i: False)
    with pytest.raises(ValueError):
        room.unhumidified_room_w([0.0], [0.5], 21.0, 101325.0, lambda i: False, fade_ach=-1.0)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kw", [
    dict(room_humidity="humid"), dict(people_gkg=-0.1), dict(people_gkg=10.5),
    dict(people_fade_ach=-1.0), dict(stack_factor=1.2), dict(stack_factor=-0.1),
])
def test_inputs_validated(kw):
    with pytest.raises(ValueError):
        base(**kw)


# ---------------------------------------------------------------------------
# Wiring through the solver
# ---------------------------------------------------------------------------

def test_fixed_mode_ignores_the_people_inputs(weather):
    a = run_lifetime(base(), weather, keep_fog=True)
    b = run_lifetime(base(people_gkg=5.0, people_fade_ach=3.0, stack_factor=1.0), weather, keep_fog=True)
    assert a.fog_years == b.fog_years
    assert a.daily_cav_dew_c == b.daily_cav_dew_c
    assert build_tables(base(), weather, None).w_room_h is None


@pytest.mark.parametrize("grams", [0.0, 300.0])
def test_hourly_path_fed_a_constant_reproduces_fixed_mode(weather, monkeypatch, grams):
    """The hourly room series runs through the tables, the breathing pass and
    the solver. Fed the fixed room's own humidity every hour, it must give the
    fixed result to the last digit."""
    fixed = base(desiccant_grams=grams)
    p = atmospheric_pressure_pa(weather.elevation_m)
    w_fixed = w_from_t_rh(fixed.t_room_c, fixed.rh_room, p_atm_pa=p)
    monkeypatch.setattr(room, "unhumidified_room_w", lambda *a, **k: [w_fixed] * weather.hours)
    a = run_lifetime(fixed, weather, keep_fog=True)
    b = run_lifetime(replace(fixed, room_humidity="unhumidified"), weather, keep_fog=True)
    assert b.tables.w_room_h is not None
    assert a.fog_years == b.fog_years
    assert a.daily_cav_dew_c == b.daily_cav_dew_c
    assert a.daily_loading == b.daily_loading
    assert a.final_loading == b.final_loading


def test_more_people_moisture_never_less_fog(weather):
    counts = [fog_hours(run_lifetime(base(room_humidity="unhumidified", people_gkg=g), weather, keep_fog=True))
              for g in (0.0, 1.2, 2.5, 5.0)]
    assert counts == sorted(counts)
    assert counts[-1] > counts[0]


def test_unhumidified_room_is_hourly_and_drier_than_35_pct_in_a_new_york_january(weather):
    inp = base(room_humidity="unhumidified")
    tb = build_tables(inp, weather, None)
    p = atmospheric_pressure_pa(weather.elevation_m)
    jan = sorted(rh_from_t_w(inp.t_room_c, tb.w_room_h[i], p_atm_pa=p) for i in range(744))
    assert len(set(jan)) > 100                                  # it moves hour to hour
    assert jan[len(jan) // 2] < 0.35                            # a heated, unhumidified NYC room is dry


def test_stack_factor_scales_the_stack_term_only(weather):
    tall = dict(building_floors=30, window_floor=28)
    full = build_tables(base(**tall), weather, None)
    half = build_tables(base(**tall, stack_factor=0.5), weather, None)
    short = build_tables(base(**tall, floor_height_m=1.8), weather, None)   # same as halving the height
    assert half.dp_pa == pytest.approx(short.dp_pa, abs=1e-9)
    assert half.dp_pa != full.dp_pa
    assert build_tables(base(**tall, stack_factor=1.0), weather, None).dp_pa == full.dp_pa


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch, weather):
    os.environ.setdefault("MAPBOX_TOKEN", "pk.test")
    os.environ.setdefault("NREL_API_KEY", "test")
    import app as flask_app
    loc = Location("x", "277 PARK AVE, NEW YORK, NY 10172", 40.7568, -73.9742)
    monkeypatch.setattr(flask_app, "get_weather_for_address", lambda *a, **k: (loc, weather, False))
    return flask_app.app.test_client()


def test_api_defaults_and_echo(client):
    d = client.get("/api/lifetime?trace=0&max_years=1").get_json()
    i = d["inputs"]
    assert (i["room_humidity"], i["people_gkg"], i["people_fade_ach"], i["stack_factor"]) == ("fixed", 1.2, 0.5, 1.0)
    hs = d["room"]["heating_season"]
    assert d["room"]["mode"] == "fixed" and hs["median_pct"] == hs["p10_pct"] == hs["p90_pct"] == pytest.approx(35.0, abs=0.1)
    pre = client.get("/api/presets").get_json()["defaults"]
    assert pre["room_humidity"] == "fixed" and pre["stack_factor"] == 1.0


def test_api_unhumidified(client):
    q = "/api/lifetime?trace=0&max_years=1&grams=0&room_humidity=unhumidified&people_gkg=1.0&people_fade_ach=1&stack_factor=0.8"
    d = client.get(q).get_json()
    i = d["inputs"]
    assert (i["room_humidity"], i["people_gkg"], i["people_fade_ach"], i["stack_factor"]) == ("unhumidified", 1.0, 1.0, 0.8)
    hs = d["room"]["heating_season"]
    assert d["room"]["mode"] == "unhumidified"
    assert hs["p10_pct"] < hs["median_pct"] < hs["p90_pct"] < 60


@pytest.mark.parametrize("q", [
    "room_humidity=wet", "people_gkg=11", "people_gkg=-1", "people_fade_ach=60", "stack_factor=1.5",
])
def test_api_rejects_bad_room_inputs(client, q):
    assert client.get("/api/lifetime?trace=0&" + q).status_code == 400
