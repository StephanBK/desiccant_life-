"""
Two questions, both answered here.

1. Does the desiccant solver with NO desiccant reproduce the earlier
   cavity-moisture model (engine.moisture.run_year, byte-identical to the
   cavity_moisture repo)? It must: the 0 g branch calls the same
   step_hour. Four things were added around it since and are switched off
   or accounted for below:
     - sealant vapour diffusion (bead_width_m=0 gives none),
     - wind entering as pressure (wind_scaling=False),
     - starting state: run_lifetime starts at the first hour's supply with
       a dry pane, run_year at room humidity (spin-up off here, so both
       start dry); the humidity difference is forgotten within hours,
     - the vent stream temperature: run_lifetime mixes outdoor and room
       air by flow, run_year uses room temperature for the whole stream,
       and run_lifetime evaluates the cavity dry-air mass at room humidity
       where run_year uses the cavity's. Both shift the cavity AIR
       temperature and dry-air mass by a fraction of a percent, not the
       cold-pane saturation ceiling or the humidity-ratio balance. Measured
       effect: yearly condensed water within 2 % (0.2 % when the room path
       dominates), identical condensing hours, hourly W_cav identical to
       1e-15 except for a handful of single hours where a film runs out at
       a slightly different minute (5 hours of 8,760 in the worst case).

2. The net contribution accounting. The mix rule is linear, so the split
   is exact; the tests below pin the balance and the physics sign:
   cold outdoor air is drier than the cavity in winter, so the OUTDOOR path
   removes water over the heating season while the ROOM path adds it.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from engine.geometry import CavityGeometry
from engine.lifetime import (
    LifetimeInputs, contribution_shares, in_heating_season, run_lifetime, split_vent_net,
)
from engine.moisture import run_year

FIXTURE = Path(__file__).parent / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz"
GEO = CavityGeometry.from_inches(60, 96, 0.6024)
WARMUP = 72          # hours ignored for the hour-by-hour comparison


@pytest.fixture(scope="module")
def weather():
    from engine.weather import parse_nsrdb_csv
    return parse_nsrdb_csv(gzip.open(FIXTURE, "rt").read())


def _lifetime_zero_g(weather, a_out, a_in):
    inp = LifetimeInputs(
        geometry=GEO, f_cold=0.30, f_warm=0.59, u_assembly=1.703,
        absorptance=0.0, sky_radiation=False, pane_coupling=False, wind_scaling=False,
        ach_out=a_out, ach_in=a_in, desiccant_grams=0.0, bead_width_m=0.0, max_years=1,
    )
    return run_lifetime(inp, weather, None, keep_year1=True, keep_daily=False)


def _run_year(weather, a_out, a_in):
    a_tot = a_out + a_in
    return run_year(
        weather.t_out_c, weather.rh_out, 0.30, 0.59, a_tot,
        vent_interior_fraction=(a_in / a_tot) if a_tot > 0 else 1.0,
        geometry=GEO, elevation_m=weather.elevation_m, substeps=1, spinup_passes=0,
        keep_hours=True, u_assembly=None,
    )


# "very loose" outdoor = the legacy weathered preset (20 ACH); the other two
# are the ends of the vent-fraction axis the old tool was built around.
EQUIV_CASES = [
    ("all_room", 0.0, 5.0),
    ("weathered_out_sealed_in", 20.0, 0.1),
    ("mixed", 1.0, 0.5),
]


@pytest.mark.parametrize("name,a_out,a_in", EQUIV_CASES)
def test_zero_desiccant_equals_original_run_year(weather, name, a_out, a_in):
    new = _lifetime_zero_g(weather, a_out, a_in)
    old = _run_year(weather, a_out, a_in)

    # Yearly condensed water, per m2: the number the old tool was built for.
    cond_new = new.years[0].condensed_kg_per_m2
    cond_old = old.total_condensed_kg_per_m2
    assert cond_new == pytest.approx(cond_old, rel=2.5e-2, abs=1e-6), (name, cond_new, cond_old)
    assert new.years[0].hours_condensing == old.hours_condensing, name

    # Hour by hour cavity humidity ratio after the warm-up: identical apart
    # from single hours where a film runs out at a different minute.
    w_new = new.year1["w_cav"]
    w_old = [h.w_cav for h in old.hours]
    assert len(w_new) == len(w_old) == 8760
    diffs = [abs(a - b) for a, b in zip(w_new[WARMUP:], w_old[WARMUP:])]
    off = sum(d > 2e-5 for d in diffs)                # kg/kg; supplies are ~1e-3..1e-2
    assert off <= 8, (name, off, max(diffs))
    assert sorted(diffs)[len(diffs) // 2] < 1e-12, name   # median: exact


def test_zero_desiccant_no_diffusion_switch_off_is_real(weather):
    """bead_width_m=0 must remove the diffusion floor entirely."""
    r = _lifetime_zero_g(weather, 1.0, 0.5)
    assert r.net_diffusion_g == 0.0 and r.years[0].heating_diffusion_g == 0.0


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------

def test_split_is_exact_and_recovers_operating_humidity():
    a_out, a_in, w_out, w_room, m, dt = 2.0, 0.5, 0.002, 0.0055, 0.02, 0.25
    a_tot = a_out + a_in
    w_sup = (a_out * w_out + a_in * w_room) / a_tot
    for w_op in (0.0, 0.001, w_sup, 0.004, 0.01):
        vent_net = a_tot * m * (w_sup - w_op) * dt
        n_out, n_in = split_vent_net(vent_net, a_out, w_out, a_in, w_room, m, dt)
        assert n_out + n_in == pytest.approx(vent_net, abs=1e-15)
        assert n_out == pytest.approx(a_out * m * (w_out - w_op) * dt, abs=1e-15)
        assert n_in == pytest.approx(a_in * m * (w_room - w_op) * dt, abs=1e-15)
    assert split_vent_net(1.0, 0.0, w_out, 0.0, w_room, m, dt) == (0.0, 0.0)


def test_shares_only_when_every_path_is_a_source():
    c = contribution_shares(40.0, 55.0, 5.0)
    assert c["total_g"] == 100.0 and c["outdoor_pct"] == pytest.approx(40.0)
    assert c["room_pct"] + c["outdoor_pct"] + c["diffusion_pct"] == pytest.approx(100.0)
    c = contribution_shares(-5.0, 100.0, 5.0)              # a remover: grams only
    assert c["total_g"] == 100.0 and c["outdoor_pct"] is None and c["room_pct"] is None
    c = contribution_shares(-5.0, 2.0, 0.0)
    assert c["total_g"] == -3.0 and c["outdoor_pct"] is None


def test_heating_season_calendar():
    assert in_heating_season(0) and in_heating_season(2159)            # Jan 1, Mar 31
    assert not in_heating_season(2160) and not in_heating_season(6551)  # Apr 1, Sep 30
    assert in_heating_season(6552) and in_heating_season(8759)         # Oct 1, Dec 31


def test_life_split_balances_water_into_desiccant(weather):
    """Over the desiccant's life: outdoor + room + diffusion = water the
    sieve took (plus the little the pane held), to a small tolerance."""
    inp = LifetimeInputs(
        geometry=GEO, f_cold=0.30, f_warm=0.59, u_assembly=1.703,
        ach_out=0.02, ach_in=0.1, wind_scaling=False, desiccant_grams=1000.0,
    )
    r = run_lifetime(inp, weather, None, keep_year1=False, keep_daily=False)
    assert r.exhausted_hour is not None
    c = r.contributions()
    taken = r.total_water_into_desiccant_g
    # the run continues past exhaustion; uptake after it is a few grams
    assert c["total_g"] == pytest.approx(taken, rel=0.05), (c["total_g"], taken)
    assert c["room_pct"] > c["outdoor_pct"] > 0 and c["diffusion_pct"] > 0
    assert c["room_pct"] + c["outdoor_pct"] + c["diffusion_pct"] == pytest.approx(100.0, abs=1e-6)


def test_cold_outdoor_air_dries_the_cavity_in_winter(weather):
    """The hypothesis under test. With no desiccant and a loose outdoor
    path, the cavity sits near outdoor humidity; over the heating season
    the outdoor path's net is NEGATIVE (it carries water out) and the
    room path's is positive. Over the full year the two nearly cancel,
    which is why the season split exists."""
    r = _lifetime_zero_g(weather, 20.0, 0.1)
    y = r.years[0]
    assert y.heating_outdoor_g < 0.0 < y.heating_room_g, (y.heating_outdoor_g, y.heating_room_g)
    # Full-year nets sum to (condensed - evaporated + inventory change) ~ 0 at 0 g
    assert abs(y.net_outdoor_g + y.net_room_g + y.net_diffusion_g) < 2.0


def test_fresh_sieve_takes_from_both_paths(weather):
    """A fresh 3A sieve pulls the cavity to ~0 humidity, so BOTH paths are
    sources while it fills, even the cold outdoor one: nothing is drier
    than the air next to a fresh sieve."""
    inp = LifetimeInputs(
        geometry=GEO, f_cold=0.30, f_warm=0.59, u_assembly=1.703,
        al_out=0.1, al_in=0.06, desiccant_grams=1000.0,
    )
    r = run_lifetime(inp, weather, None, keep_year1=False, keep_daily=False)
    c = r.contributions()
    assert c["outdoor_g"] > 0 and c["room_g"] > 0
    assert 0 < c["outdoor_pct"] < 100 and 0 < c["room_pct"] < 100


# ---------------------------------------------------------------------------
# Signed, two-sided sealant diffusion
# ---------------------------------------------------------------------------

def test_split_exchange_net_signs_each_path_by_its_own_gradient():
    """A bead facing a side drier than the cavity carries water OUT even
    while the other bead carries water in."""
    from engine.lifetime import split_exchange_net
    m, dt = 0.01, 1.0
    a_out, ad_out, a_in, ad_in = 0.0, 0.002, 0.0, 0.002
    w_out, w_room = 0.001, 0.006
    # operating humidity between the two: net = sum of the two bead terms
    w_op = 0.004
    net = (ad_out * (w_out - w_op) + ad_in * (w_room - w_op)) * m * dt
    n_out, n_in, n_diff = split_exchange_net(net, a_out, ad_out, w_out, a_in, ad_in, w_room, m, dt)
    assert n_out == 0.0 and n_in == 0.0
    assert n_diff == pytest.approx(net)
    assert ad_out * (w_out - w_op) < 0 < ad_in * (w_room - w_op)   # outdoor bead dries, room bead wets


def test_beads_alone_cannot_push_the_cavity_above_its_wetter_neighbour(weather):
    """No vents, no loops, no breathing, no desiccant: the only exchange is
    the two silicone beads, each driven by its own vapour-pressure gradient.
    The cavity humidity can then never exceed the wetter of the two sides
    (room, or the outdoor air of the recent past). The old dry-cavity
    inflow violated this: it kept adding water with the cavity already
    wetter than both neighbours."""
    inp = LifetimeInputs(
        geometry=GEO, f_cold=0.014, f_warm=0.59, u_assembly=0.9,
        t_room_c=21.1, rh_room=0.30, al_out=0.0, al_in=0.0, loops=False, breathing=False,
        desiccant_grams=0.0, absorptance=0.0, sky_radiation=False, max_years=1,
    )
    r = run_lifetime(inp, weather, None, keep_year1=True, keep_daily=False)
    w_cav = r.year1["w_cav"]; w_out = r.tables.w_out; w_room = r.tables.w_room
    film = r.year1["film_kg"]
    window = 24 * 14                      # the bead exchange is slow: allow a two-week memory of outdoor air
    worst = 0.0; checked = 0
    for i in range(WARMUP, len(w_cav)):
        # Liquid stored on the pane in a cold spell re-evaporates on a warm
        # day and can lift the air above both neighbours; that is real. The
        # bound is on hours with no stored water.
        if any(f > 0.0 for f in film[max(0, i - 24):i + 1]):
            continue
        checked += 1
        cap = max(w_room, max(w_out[max(0, i - window):i + 1]))
        worst = max(worst, w_cav[i] - cap)
    assert checked > 1000
    assert worst <= 1e-5, worst           # kg/kg; supplies are 1e-3..1e-2
    # and the two beads are a net REMOVER over the year in a room-side-dry, winter-dry cavity
    # is not guaranteed, but the net must stay below the dry-cavity bound.
    bound_g = sum(r.tables.diff_kg_per_m2_h) * 1000.0 * GEO.glazing_area_m2
    assert r.net_diffusion_g <= bound_g
