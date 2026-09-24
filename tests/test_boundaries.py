"""
Year-boundary continuity guard (2026-09-23).

The typical weather year plays on repeat, so Dec 31 23:00 of year N flows
straight into Jan 1 00:00 of year N+1. Stephan reported seeing no fog at the
end of year 1 and fog right at the start of year 2. Not reproduced (60
scenario-years), and the engine carries its state; this guard makes sure it
always will. It checks, at every year boundary of a scenario grid:

  1. the state (pane film, cavity humidity, desiccant loading) the next
     year starts from IS the state the old year ended with;
  2. the film changes across New Year's midnight no more than it changes in
     the neighbouring hours (no fog "from nothing" at the boundary);
  3. the weather file itself is continuous at the year end.

A real physical start of fog in early January (for example a desiccant that
fills in late December) passes: it grows hour by hour like any other hour.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from engine import psychro
from engine.cavity import f_warm_estimate
from engine.geometry import CavityGeometry
from engine.lifetime import LifetimeInputs, run_lifetime
from engine.weather import parse_nsrdb_csv

FIXTURE = Path(__file__).parent / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz"
U = psychro.u_ip_to_si(0.16)
R = psychro.r_ip_to_si(0.97)

#          f_cold  al_out  al_in   grams   room RH  desorption   what it covers
SCENARIOS = [
    (0.014, 0.005, 0.005, 0.0, 0.50, True),     # no desiccant, thick winter film carried over New Year
    (0.068, 0.10, 0.06, 0.0, 0.30, True),       # no desiccant, single pane, moderate seals
    (0.014, 1.00, 0.30, 200.0, 0.40, True),     # leaky, small sieve full within days, fog both winters
    (0.014, 0.005, 0.005, 900.0, 0.50, True),   # fills mid year 1, first winter after saturation
    (0.014, 0.005, 0.005, 3628.739, 0.30, True),   # 277 default: 8 lb, desorption on
    (0.014, 0.005, 0.005, 3628.739, 0.30, False),  # same, desorption off
]


@pytest.fixture(scope="module")
def weather():
    return parse_nsrdb_csv(gzip.open(FIXTURE, "rt").read())


def _inputs(f, ao, ai, g, rh, desorb):
    return LifetimeInputs(
        geometry=CavityGeometry.from_inches(60, 96, 0.6), f_cold=f, f_warm=f_warm_estimate(f, R, U),
        u_assembly=U, t_room_c=psychro.f_to_c(70), rh_room=rh, al_out=ao, al_in=ai,
        desiccant_grams=g, allow_desorption=desorb, absorptance=0.1, building_floors=50, window_floor=25,
        facade_azimuth_deg=0.0, max_years=2,
    )


@pytest.fixture(scope="module")
def runs(weather):
    out = []
    for sc in SCENARIOS:
        r = run_lifetime(_inputs(*sc), weather, keep_year1=False, keep_daily=False,
                         years_after_full=1, keep_boundaries=True)
        out.append((sc, r))
    return out


def _crossed(r):
    """Boundaries that were actually crossed (the last year end has no next year)."""
    return [b for b in r.boundaries if "next_start" in b]


def test_every_scenario_crosses_at_least_one_boundary(runs):
    for sc, r in runs:
        assert _crossed(r), sc


def test_state_carries_over_exactly(runs):
    for sc, r in runs:
        for b in _crossed(r):
            assert b["next_start"] == b["end"], (sc, b["year"])


def test_film_does_not_jump_at_new_year(runs):
    for sc, r in runs:
        for b in _crossed(r):
            tail, head = b["tail_film"], b["head_film"]
            assert len(tail) == 24 and len(head) == 24, (sc, b["year"])
            seq = tail + head
            steps = [abs(seq[k + 1] - seq[k]) for k in range(len(seq) - 1)]
            boundary = steps[23]                          # Dec 31 23:00 -> Jan 1 00:00
            neighbours = steps[:23] + steps[24:]
            # no bigger than the neighbouring hours allow, with a 0.1 um floor
            assert boundary <= 1.5 * max(neighbours) + 1e-7, (sc, b["year"], boundary, max(neighbours))


def test_weather_file_is_continuous_at_the_year_end(weather):
    for series in (weather.t_out_c, weather.rh_out):
        steps = sorted(abs(series[k + 1] - series[k]) for k in range(len(series) - 1))
        p99 = steps[int(0.99 * (len(steps) - 1))]
        assert abs(series[0] - series[-1]) <= p99, (series[-1], series[0], p99)


def test_recorder_is_off_by_default(weather):
    r = run_lifetime(_inputs(*SCENARIOS[1]), weather, keep_year1=False, keep_daily=False)
    assert r.boundaries == []


def test_hermetic_cavity_does_not_breathe(weather):
    """Found while writing this guard: with zero leakage on BOTH layers the
    breathing flow used to be added anyway and attributed to the room side
    (0.57 g of room water into a 17 g sieve in a year). No path, no flow."""
    from engine.lifetime import build_tables
    inp = LifetimeInputs(geometry=CavityGeometry.from_inches(31, 28, 1.0), f_cold=0.125, f_warm=0.5, u_assembly=1.7,
                         t_room_c=22.0, rh_room=0.5, al_out=0.0, al_in=0.0, desiccant_grams=17.0, tau_hours=1.0,
                         allow_desorption=False, pane_coupling=False, absorptance=0.0, sky_radiation=False, max_years=1)
    tb = build_tables(inp, weather, None)
    assert max(tb.ach_total) == 0.0
    r = run_lifetime(inp, weather, keep_year1=False, keep_daily=False)
    assert r.years[0].net_room_g == 0.0 and r.years[0].net_outdoor_g == 0.0
    # one side open: breathing flows, and only through that side
    tb2 = build_tables(replace_al(inp, 0.0, 0.3), weather, None)
    assert max(tb2.ach_total) > 0.0 and max(tb2.ach_out) == 0.0


def replace_al(inp, al_out, al_in):
    from dataclasses import replace
    return replace(inp, al_out=al_out, al_in=al_in)
