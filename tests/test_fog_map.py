"""Opt-in hourly fog map, years simulated after the desiccant fills, and the
first VISIBLE fog hour (2026-09-23, for the 277 Park app).

The contract tested here:
  - off by default, and when off the run is identical to the original;
  - the map agrees hour for hour with YearSummary.hours_visible;
  - years_after_full adds whole years AFTER the fill year and never
    changes anything up to and including the fill year;
  - the API exposes both behind query parameters and rejects bad values.
"""

from __future__ import annotations

import gzip
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from engine.geometry import CavityGeometry
from engine.lifetime import FOG_LEVELS, LifetimeInputs, fog_level, run_lifetime
from engine.moisture import MAX_SURFACE_FILM_KG_PER_M2, VISIBLE_FILM_KG_PER_M2
from engine.weather import Location, parse_nsrdb_csv

FIXTURE = Path(__file__).parent / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz"
VIS = VISIBLE_FILM_KG_PER_M2
CAP = MAX_SURFACE_FILM_KG_PER_M2


@pytest.fixture(scope="module")
def weather():
    return parse_nsrdb_csv(gzip.open(FIXTURE, "rt").read())


@pytest.fixture
def leaky():
    """Loose two-path venting, 50 g: fills within days and fogs in year 1."""
    return LifetimeInputs(
        geometry=CavityGeometry.from_inches(60, 96, 0.6024),
        f_cold=0.30, f_warm=0.59, u_assembly=1.703,
        ach_out=1.0, ach_in=0.5, desiccant_grams=50.0,
        absorptance=0.0, sky_radiation=False,
    )


# ---------------------------------------------------------------------------
# fog_level
# ---------------------------------------------------------------------------

def test_fog_level_zero_at_and_below_threshold():
    assert fog_level(0.0, VIS, CAP) == 0
    assert fog_level(VIS, VIS, CAP) == 0


def test_fog_level_one_just_above_threshold_and_top_at_cap():
    assert fog_level(VIS * 1.0001, VIS, CAP) == 1
    assert fog_level(CAP, VIS, CAP) == FOG_LEVELS
    assert fog_level(CAP * 10, VIS, CAP) == FOG_LEVELS


def test_fog_level_monotone_and_bounded():
    films = [VIS * (CAP / VIS) ** (i / 200) for i in range(1, 201)]
    levels = [fog_level(f, VIS, CAP) for f in films]
    assert levels == sorted(levels)
    assert set(levels) == set(range(1, FOG_LEVELS + 1))


def test_fog_level_zero_threshold_is_finite():
    # visible_um = 0 is a legal API value ("any liquid"); the log scale
    # must not divide by zero.
    assert fog_level(1e-9, 0.0, CAP) == 1
    assert fog_level(CAP, 0.0, CAP) == FOG_LEVELS


# ---------------------------------------------------------------------------
# Solver: default path unchanged
# ---------------------------------------------------------------------------

def test_default_run_is_unchanged_by_the_new_options(leaky, weather):
    a = run_lifetime(leaky, weather)
    b = run_lifetime(leaky, weather, keep_fog=True)
    assert a.fog_years == []
    assert a.exhausted_hour == b.exhausted_hour
    assert a.first_condensation_hour == b.first_condensation_hour
    assert [asdict(y) for y in a.years] == [asdict(y) for y in b.years]
    assert a.daily_film_max_kg == b.daily_film_max_kg


def test_bad_years_after_full_rejected(leaky, weather):
    with pytest.raises(ValueError):
        run_lifetime(leaky, weather, years_after_full=6)
    with pytest.raises(ValueError):
        run_lifetime(leaky, weather, years_after_full=-1)


# ---------------------------------------------------------------------------
# Solver: the map
# ---------------------------------------------------------------------------

def test_map_matches_hours_visible_year_by_year(leaky, weather):
    r = run_lifetime(leaky, weather, keep_fog=True, years_after_full=1)
    assert len(r.fog_years) == r.years_run == len(r.years)
    for s, y in zip(r.fog_years, r.years):
        if y.hours_visible == 0:
            assert s is None
        else:
            assert len(s) == 8760
            assert set(s) <= set("0123456789")
            assert sum(ch != "0" for ch in s) == y.hours_visible


def test_first_visible_hour_is_first_nonzero_cell(leaky, weather):
    cold = replace(leaky, f_cold=0.014, f_warm=0.13)       # VIG-like cold pane
    r = run_lifetime(cold, weather, keep_fog=True, years_after_full=1)
    flat = "".join(s if s is not None else "0" * 8760 for s in r.fog_years)
    first = next((i for i, ch in enumerate(flat) if ch != "0"), None)
    assert r.first_visible_hour == first
    assert r.first_visible_hour is not None
    # Visible needs more film than "any condensation", so it cannot come first.
    assert r.first_visible_hour >= r.first_condensation_hour


def test_first_visible_hour_computed_without_the_map(leaky, weather):
    a = run_lifetime(leaky, weather)
    b = run_lifetime(leaky, weather, keep_fog=True)
    assert a.first_visible_hour == b.first_visible_hour


# ---------------------------------------------------------------------------
# Solver: years_after_full
# ---------------------------------------------------------------------------

def test_years_after_full_adds_whole_years_and_keeps_the_life(leaky, weather):
    a = run_lifetime(leaky, weather)
    b = run_lifetime(leaky, weather, years_after_full=2)
    assert a.exhausted_hour is not None
    assert b.exhausted_hour == a.exhausted_hour
    assert b.years_run == a.years_run + 2
    assert b.hours_run == a.hours_run + 2 * 8760
    # Everything up to and including the fill year is identical.
    assert [asdict(y) for y in b.years[: a.years_run]] == [asdict(y) for y in a.years]
    assert b.contributions() == a.contributions()


def test_years_after_full_does_not_extend_a_run_that_never_fills(weather):
    # Tight, big sieve, one year allowed: does not fill in year 1.
    inp = LifetimeInputs(
        geometry=CavityGeometry.from_inches(60, 96, 0.6),
        f_cold=0.014, f_warm=0.13, u_assembly=0.91,
        ach_out=0.0, ach_in=0.0, desiccant_grams=3000.0,
        absorptance=0.1, max_years=1,
    )
    r = run_lifetime(inp, weather, keep_fog=True, years_after_full=3)
    assert r.exhausted_hour is None
    assert r.years_run == 1 and len(r.fog_years) == 1


def test_no_desiccant_runs_max_years_regardless(leaky, weather):
    inp = replace(leaky, desiccant_grams=0.0, max_years=2)
    r = run_lifetime(inp, weather, keep_fog=True, years_after_full=2)
    assert r.exhausted_hour is None and r.years_run == 2


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


LEAKY_Q = "al_out=aged&al_in=certified_typical&grams=200&trace=0"


def test_api_without_fog_map_has_no_fog_key(client):
    d = client.get(f"/api/lifetime?{LEAKY_Q}").get_json()
    assert "fog" not in d
    assert "first_visible_hour" in d["headline"]


def test_api_fog_map_shape(client):
    d = client.get(f"/api/lifetime?{LEAKY_Q}&fog_map=1&years_after_full=1").get_json()
    f = d["fog"]
    assert f["levels"] == FOG_LEVELS and f["scale"] == "log"
    assert f["visible_um"] == pytest.approx(5.0) and f["max_um"] == pytest.approx(100.0)
    assert f["years_after_full"] == 1
    assert len(f["years"]) == d["headline"]["years_run"] == len(d["years"])
    for s, y in zip(f["years"], d["years"]):
        assert (s is None) == (y["hours_visible"] == 0)
        if s is not None:
            assert len(s) == 8760
    h = d["headline"]
    assert h["first_visible_hour"] is not None
    assert h["first_visible_days"] == pytest.approx(h["first_visible_hour"] / 24.0, abs=0.05)


def test_api_years_after_full_extends_run(client):
    a = client.get(f"/api/lifetime?{LEAKY_Q}").get_json()["headline"]
    b = client.get(f"/api/lifetime?{LEAKY_Q}&years_after_full=1").get_json()["headline"]
    assert a["exhausted_hour"] == b["exhausted_hour"]
    assert b["years_run"] == a["years_run"] + 1


def test_api_rejects_bad_years_after_full(client):
    r = client.get(f"/api/lifetime?{LEAKY_Q}&years_after_full=9")
    assert r.status_code == 400
