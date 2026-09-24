"""
Parity with the 277 Park app (2026-09-23).

The old simulator (this repo's frontend, embedded in Odoo) and the 277 Park
app (StephanBK/park277-desiccant) call the same engine. Stephan saw
different results: the engine was identical (proven byte for byte on the
live API), the differences were the old app's starting inputs, its run
stopping in the fill year, and its "first fog" meaning any trace of liquid.
These tests pin the fix.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pytest

from engine.geometry import CavityGeometry
from engine.lifetime import LifetimeInputs, run_lifetime
from engine.weather import Location, parse_nsrdb_csv

HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz"
FRONTEND_DEFAULTS = HERE.parent / "frontend" / "src" / "defaults.json"

# The 277 Park app's engine request for its default scenario, mirrored from
# park277-desiccant server/engine.js engineParams(DEFAULTS). Its own test
# suite pins the same values from the other side.
PARK277_DEFAULT_REQUEST = dict(
    address="277 Park Avenue, New York, NY 10172", orientation="north",
    width_in=60, height_in=96, offset_in=0.6, u_ip=0.16, r_ip=0.97,
    desiccant="ms3a", desorption="true", absorptance=0.1, floors=50, window_floor=25,
    p_occ_pa=5, p_unocc_pa=0, occ_start_h=7, occ_end_h=19, weekdays_only="true",
    sealant_out="silicone", sealant_in="silicone", max_years=20,
    f_cold=0.014, al_out="wet_sealed", al_in="wet_sealed", grams=3628.739, t_in=70, rh_in=30,
    trace="false", fog_map="true", years_after_full=1,
)


@pytest.fixture(scope="module")
def weather():
    return parse_nsrdb_csv(gzip.open(FIXTURE, "rt").read())


@pytest.fixture
def client(monkeypatch, weather):
    os.environ.setdefault("MAPBOX_TOKEN", "pk.test")
    os.environ.setdefault("NREL_API_KEY", "test")
    import app as flask_app
    loc = Location("x", "277 PARK AVE, NEW YORK, NY 10172", 40.7555, -73.975)
    monkeypatch.setattr(flask_app, "get_weather_for_address", lambda *a, **k: (loc, weather, False))
    return flask_app.app.test_client()


def _frontend_query() -> dict:
    """The old app's first-load request, built the way frontend/src/api.js
    toQuery builds it (empty values dropped, booleans as 1/0)."""
    d = json.loads(FRONTEND_DEFAULTS.read_text())
    return {k: (("1" if v else "0") if isinstance(v, bool) else v) for k, v in d.items() if v not in ("", None)}


# ------------------------------------------------------------ fog days

def test_days_visible_counts_days_with_any_visible_hour(weather):
    inp = LifetimeInputs(
        geometry=CavityGeometry.from_inches(60, 96, 0.6), f_cold=0.014, f_warm=0.13, u_assembly=0.91,
        ach_out=1.0, ach_in=0.5, desiccant_grams=50.0, absorptance=0.0, sky_radiation=False,
    )
    r = run_lifetime(inp, weather, keep_fog=True, years_after_full=1)
    assert any(y.days_visible for y in r.years)
    for s, y in zip(r.fog_years, r.years):
        expect = 0 if s is None else sum(1 for d in range(365) if any(ch != "0" for ch in s[d * 24:(d + 1) * 24]))
        assert y.days_visible == expect
        assert y.days_visible <= min(365, y.hours_visible)


def test_headline_fog_days_is_the_last_year(client):
    d = client.get("/api/lifetime?" + "&".join(f"{k}={v}" for k, v in PARK277_DEFAULT_REQUEST.items())).get_json()
    assert d["headline"]["fog_days_per_year"] == d["years"][-1]["days_visible"]
    assert "days_visible" in d["years"][0]


# ------------------------------------------------------------ sweep and export

def test_sweep_points_carry_visible_fog_and_run_past_saturation(client):
    q = "al_out=aged&al_in=certified_typical&grams=100&x_key=desiccant_grams&x_values=100,200"
    a = client.get(f"/api/sweep?{q}").get_json()["points"]
    b = client.get(f"/api/sweep?{q}&years_after_full=1").get_json()["points"]
    for p in a + b:
        assert "first_visible_hour" in p and "fog_days_per_year" in p
    assert all(pb["years_run"] == pa["years_run"] + 1 for pa, pb in zip(a, b) if pa["exhausted_hour"] is not None)


def test_export_accepts_years_after_full(client):
    r = client.get("/api/export.xlsx?al_out=aged&al_in=certified_typical&grams=100&max_years=2&years_after_full=1")
    assert r.status_code == 200 and r.data[:2] == b"PK"


# ------------------------------------------------------------ defaults

def test_default_address_has_the_zip():
    import app as flask_app
    assert flask_app.DEFAULTS["address"].endswith("NY 10172")


def test_frontend_defaults_are_the_277_scenario():
    d = json.loads(FRONTEND_DEFAULTS.read_text())
    for k, v in PARK277_DEFAULT_REQUEST.items():
        if k in ("trace", "fog_map"):
            continue
        got = d[k]
        want = {"true": True, "false": False}.get(v, v) if isinstance(v, str) else v
        assert got == want, f"{k}: old app default {got!r}, 277 app {want!r}"


def test_old_app_and_277_app_get_identical_results(client):
    """The whole point: same inputs, same engine, same numbers."""
    a = client.get("/api/lifetime?" + "&".join(f"{k}={v}" for k, v in PARK277_DEFAULT_REQUEST.items())).get_json()
    old = dict(_frontend_query(), trace="false", fog_map="true")
    b = client.get("/api/lifetime?" + "&".join(f"{k}={v}" for k, v in old.items())).get_json()
    assert a["headline"] == b["headline"]
    assert a["years"] == b["years"]
    assert a["fog"] == b["fog"]
