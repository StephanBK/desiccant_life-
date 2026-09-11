"""
ANLY-003: desiccant, two-path venting, lifetime solver, sweeps.

Numbers pinned here are the ones the Explain page quotes. If a physics
constant changes, the page and these tests change together.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from engine.cavity import vent_cold_surface_rise, vent_cold_surface_rise_two_path
from engine.desiccant import DESICCANTS, cartridge_volume_ml, uptake_step, water_removed_kg
from engine.geometry import CavityGeometry
from engine.lifetime import (
    ACH_IN_PRESETS, ACH_OUT_PRESETS, LifetimeInputs, build_tables, run_lifetime,
    wind_scaled_ach,
)
from engine.sweep import SWEEPABLE, sweep_1d, sweep_2d

FIXTURE = Path(__file__).parent / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz"
MS3A = DESICCANTS["ms3a"]


@pytest.fixture(scope="module")
def weather():
    from engine.weather import parse_nsrdb_csv
    return parse_nsrdb_csv(gzip.open(FIXTURE, "rt").read())


@pytest.fixture
def base():
    return LifetimeInputs(
        geometry=CavityGeometry.from_inches(60, 96, 0.6024),
        f_cold=0.30, f_warm=0.59, u_assembly=1.703,
        ach_out=1.0, ach_in=0.5, desiccant_grams=50.0,
        absorptance=0.0, sky_radiation=False,
    )


# ---------------------------------------------------------------------------
# Isotherm
# ---------------------------------------------------------------------------

def test_3a_isotherm_anchors_at_25c():
    assert MS3A.q_eq(0.50, 25.0) == pytest.approx(0.203, abs=0.005)
    assert MS3A.q_eq(0.10, 25.0) == pytest.approx(0.180, abs=0.005)
    assert MS3A.q_eq(0.01, 25.0) == pytest.approx(0.079, abs=0.005)
    assert MS3A.q_eq(0.0, 25.0) == 0.0


def test_capacity_falls_with_temperature():
    assert MS3A.q_eq(0.5, 60.0) < MS3A.q_eq(0.5, 25.0)
    assert MS3A.q_max(0.0) == MS3A.q_max(25.0)          # no cold bonus, by design
    assert MS3A.q_max(60.0) == pytest.approx(0.21 * (1 - 0.005 * 35), rel=1e-9)


def test_isotherm_is_monotone_and_bounded():
    prev = -1.0
    for rh in (0.0, 0.001, 0.01, 0.05, 0.1, 0.3, 0.6, 1.0, 1.5):
        q = MS3A.q_eq(rh, 20.0)
        assert q >= prev and q <= MS3A.q_max(20.0)
        prev = q


def test_rh_eq_inverts_q_eq():
    for rh in (0.005, 0.05, 0.3, 0.8):
        q = MS3A.q_eq(rh, 15.0)
        assert MS3A.rh_eq(q, 15.0) == pytest.approx(rh, rel=1e-9)
    assert MS3A.rh_eq(0.0, 15.0) == 0.0
    assert MS3A.rh_eq(MS3A.q_max(15.0), 15.0) == 1.0


def test_a_nearly_full_sieve_loses_grip():
    """Half full holds air near 1 % RH; 95 % full is up around 15-30 %.
    This is why 'full' is asymptotic and the rh_eq trace matters."""
    assert MS3A.rh_eq(0.5 * MS3A.q_max(20.0), 20.0) < 0.03
    assert 0.10 < MS3A.rh_eq(0.95 * MS3A.q_max(20.0), 20.0) < 0.40


# ---------------------------------------------------------------------------
# Uptake
# ---------------------------------------------------------------------------

def test_uptake_is_exact_exponential():
    import math
    q = uptake_step(0.0, 0.2, tau_hours=2.0, dt_hours=2.0)
    assert q == pytest.approx(0.2 * (1 - math.exp(-1)), rel=1e-12)


def test_uptake_never_overshoots():
    assert uptake_step(0.0, 0.2, 0.01, 100.0) == pytest.approx(0.2, abs=1e-12)


def test_desorption_gated_by_flag():
    assert uptake_step(0.2, 0.1, 2.0, 1.0, allow_desorption=False) == 0.2
    assert uptake_step(0.2, 0.1, 2.0, 1.0, allow_desorption=True) < 0.2


def test_water_removed_scales_with_mass():
    assert water_removed_kg(0.10, 0.12, 0.05) == pytest.approx(0.001)
    assert water_removed_kg(0.12, 0.10, 0.05) == pytest.approx(-0.001)


def test_cartridge_volume():
    assert cartridge_volume_ml(70.0, MS3A) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Two-path pane coupling and wind
# ---------------------------------------------------------------------------

def test_two_path_reduces_to_single_path():
    one = vent_cold_surface_rise(2.8, 21.0, 0.3, 1.703, 20.0)
    two = vent_cold_surface_rise_two_path(2.8, 21.0, -5.0, 0.3, 1.703, 20.0, 0.0)
    assert two == pytest.approx(one, rel=1e-12)


def test_outdoor_stream_cools_and_room_stream_warms():
    only_out = vent_cold_surface_rise_two_path(2.8, 21.0, -5.0, 0.3, 1.703, 0.0, 20.0)
    only_in = vent_cold_surface_rise_two_path(2.8, 21.0, -5.0, 0.3, 1.703, 20.0, 0.0)
    assert only_out < 0.0 < only_in
    assert abs(only_out) < only_in            # pane already near T_out


def test_wind_scaling_anchors():
    assert wind_scaled_ach(1.0, 4.0) == pytest.approx(1.0)
    assert wind_scaled_ach(1.0, 0.0) == pytest.approx(0.3)
    assert wind_scaled_ach(1.0, 8.0) == pytest.approx(0.3 + 0.7 * 2 ** 1.3)
    assert wind_scaled_ach(1.0, -1.0) == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Lifetime solver
# ---------------------------------------------------------------------------

def test_inputs_validate():
    geo = CavityGeometry.from_inches(60, 96, 0.6)
    with pytest.raises(ValueError):
        LifetimeInputs(geometry=geo, f_cold=1.2, f_warm=0.5, u_assembly=1.7)
    with pytest.raises(ValueError):
        LifetimeInputs(geometry=geo, f_cold=0.3, f_warm=0.5, u_assembly=1.7, desiccant_key="silica")
    with pytest.raises(ValueError):
        LifetimeInputs(geometry=geo, f_cold=0.3, f_warm=0.5, u_assembly=1.7, ach_out=-1)


def test_tables_have_one_entry_per_hour(base, weather):
    tb = build_tables(base, weather, None)
    assert tb.n == weather.hours == len(tb.w_supply) == len(tb.t_cold_c)


def test_supply_is_flow_weighted_mix(base, weather):
    tb = build_tables(base, weather, None)
    i = 100
    a_out, a_in = tb.ach_out[i], base.ach_in
    expect = (a_out * tb.w_out[i] + a_in * tb.w_room) / (a_out + a_in)
    assert tb.w_supply[i] == pytest.approx(expect, rel=1e-12)


def test_water_balance_closes_on_the_desiccant(base, weather):
    """Total water into the desiccant equals mass x loading, per window."""
    r = run_lifetime(base, weather)
    area = base.geometry.glazing_area_m2
    expect_g = r.final_loading * base.desiccant_grams
    assert r.total_water_into_desiccant_g == pytest.approx(expect_g, rel=1e-6)


def test_typical_leakage_exhausts_50g_in_days(base, weather):
    r = run_lifetime(base, weather)
    assert r.exhausted_hour is not None and r.exhausted_hour < 24 * 7
    assert r.years_run == 1
    assert r.hours_per_gram == pytest.approx(r.exhausted_hour / 50.0)


def test_lifetime_rises_with_mass_and_falls_with_leakage(base, weather):
    from dataclasses import replace
    r50 = run_lifetime(base, weather)
    r200 = run_lifetime(replace(base, desiccant_grams=200.0), weather)
    leaky = run_lifetime(replace(base, ach_out=ACH_OUT_PRESETS["weathered"]), weather)
    assert r200.exhausted_hour > r50.exhausted_hour
    assert leaky.exhausted_hour < r50.exhausted_hour


def test_hermetic_cavity_lasts_a_season(base, weather):
    from dataclasses import replace
    r = run_lifetime(replace(base, ach_out=0.002, ach_in=0.005), weather)
    assert r.exhausted_hour is not None
    assert 24 * 60 < r.exhausted_hour < 24 * 365


def test_no_desiccant_runs_all_years_and_fogs(base, weather):
    from dataclasses import replace
    r = run_lifetime(replace(base, desiccant_grams=0.0, max_years=2), weather)
    assert r.exhausted_hour is None and r.hours_per_gram is None
    assert r.years_run == 2
    assert r.first_condensation_hour is not None


def test_run_finishes_the_exhaustion_year(base, weather):
    r = run_lifetime(base, weather)
    assert r.hours_run == weather.hours
    assert len(r.year1["loading"]) == weather.hours
    assert len(r.daily_loading) == weather.hours // 24


def test_desorption_toggle_changes_answer(base, weather):
    """Desorption only matters where the vents can carry released water
    away or the pane can catch it. At hermetic leakage the toggle is
    (correctly) almost inert; at moderate leakage with a large sieve it
    extends life."""
    from dataclasses import replace
    mod = replace(base, ach_out=0.5, ach_in=0.5, desiccant_grams=200, absorptance=0.10, sky_radiation=True, max_years=2)
    a = run_lifetime(mod, weather)
    b = run_lifetime(replace(mod, allow_desorption=True), weather)
    qa, qb = a.year1["loading"], b.year1["loading"]
    assert all(y >= x - 1e-12 for x, y in zip(qa, qa[1:]))                 # one-way: never falls
    assert any(y < x - 1e-12 for x, y in zip(qb, qb[1:]))                  # two-way: releases when hot/dry
    assert b.years[0].condensed_kg_per_m2 < a.years[0].condensed_kg_per_m2  # released water leaves via vents, less on the pane
    assert all(x >= 0.0 for x in qb)


def test_year1_trace_loading_is_monotone_without_desorption(base, weather):
    r = run_lifetime(base, weather)
    q = r.year1["loading"]
    assert all(b >= a - 1e-15 for a, b in zip(q, q[1:]))


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------

def test_sweepable_covers_the_request():
    for k in ("desiccant_grams", "ach_out", "ach_in", "rh_room", "t_room_c",
              "width_m", "height_m", "offset_m"):
        assert k in SWEEPABLE


def test_1d_grams_sweep_is_monotone(base, weather):
    pts = sweep_1d(base, weather, "desiccant_grams", [10, 50, 200])
    hrs = [p.exhausted_hour for p in pts]
    assert hrs == sorted(hrs) and len(set(hrs)) == 3


def test_1d_geometry_sweep_rebuilds_tables(base, weather):
    pts = sweep_1d(base, weather, "offset_m", [0.0153, 0.05])
    assert pts[0].exhausted_hour != pts[1].exhausted_hour


def test_2d_grid_shape_and_content(base, weather):
    grid = sweep_2d(base, weather, "desiccant_grams", [20, 100], "ach_out", [0.2, 5.0])
    assert len(grid) == 2 and all(len(row) == 2 for row in grid)
    assert grid[0][0].y == 0.2 and grid[1][1].x == 100
    # more leakage, shorter life, at fixed mass
    assert grid[1][0].exhausted_hour < grid[0][0].exhausted_hour


def test_sweep_rejects_bad_keys(base, weather):
    with pytest.raises(ValueError):
        sweep_1d(base, weather, "moon_phase", [1])
    with pytest.raises(ValueError):
        sweep_2d(base, weather, "ach_in", [1], "ach_in", [2])



# ---------------------------------------------------------------------------
# Rated air leakage -> ACH (engine.leakage)
# ---------------------------------------------------------------------------

def test_leakage_conversion_anchors():
    from engine.leakage import ach_from_air_leakage, air_leakage_from_ach, wind_pressure_pa, stack_pressure_pa
    off = 0.6024 * 0.0254
    # AERC baseline single-pane at 2 Pa: a few hundred ACH in a 0.6 in cavity
    assert 200 < ach_from_air_leakage(2.0, 2.0, off) < 260
    # best certified insert at 3 Pa: order 10 ACH
    assert 5 < ach_from_air_leakage(0.06, 3.0, off) < 12
    # deeper cavity dilutes linearly
    assert ach_from_air_leakage(0.06, 3.0, 4 * off) == pytest.approx(ach_from_air_leakage(0.06, 3.0, off) / 4)
    # round trip
    assert air_leakage_from_ach(ach_from_air_leakage(0.3, 3.0, off), 3.0, off) == pytest.approx(0.3)
    # pressure anchors quoted in the docstring
    assert stack_pressure_pa(2.44, 25.0) == pytest.approx(2.5, abs=0.1)
    assert wind_pressure_pa(4.0) == pytest.approx(5.8, abs=0.1)
    assert ach_from_air_leakage(0.06, 0.0, off) == 0.0


def test_inputs_derive_ach_from_al(base):
    from dataclasses import replace
    from engine.leakage import ach_from_air_leakage
    inp = replace(base, al_out=0.10, al_in=0.06, dp_pa=3.0)
    assert inp.ach_out == pytest.approx(ach_from_air_leakage(0.10, 3.0, base.geometry.offset_m))
    assert inp.ach_in == pytest.approx(ach_from_air_leakage(0.06, 3.0, base.geometry.offset_m))
    # changing offset via sweep recomputes the derived ACH
    from engine.sweep import _with
    deeper = _with(inp, "offset_m", 4 * base.geometry.offset_m)
    assert deeper.ach_in == pytest.approx(inp.ach_in / 4)


def test_wind_enters_as_pressure_when_al_given(base, weather):
    from dataclasses import replace
    inp = replace(base, al_out=0.10, al_in=0.06, wind_scaling=True)
    tb = build_tables(inp, weather, None)
    calm = replace(inp, wind_scaling=False)
    tb0 = build_tables(calm, weather, None)
    assert all(a >= b for a, b in zip(tb.ach_out, tb0.ach_out))     # wind only adds pressure
    assert max(tb.ach_out) > 1.5 * tb0.ach_out[0]                    # and it matters on a windy hour
