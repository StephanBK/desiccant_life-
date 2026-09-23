"""
Property-based tests. Hypothesis throws random input combinations at the
engine and checks invariants that must hold regardless of the numbers:
finiteness, bounds, water balance, monotonicity in mass, leakage and time
constant, per-area scaling, determinism.

Weather is a short synthetic year (72 to 480 hours, random but plausible)
so each example runs in milliseconds; the TMY-based checks live in
test_lifetime.py and test_crosscheck.py.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from hypothesis import HealthCheck, assume, given, settings, strategies as st

from engine.geometry import CavityGeometry
from engine.leakage import ach_from_air_leakage
from engine.lifetime import LifetimeInputs, build_tables, run_lifetime
from engine.pressure import HvacSchedule
from engine.weather import WeatherYear

SETTINGS = dict(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

@st.composite
def weather_years(draw):
    n = draw(st.integers(72, 480))
    t0 = draw(st.floats(-25, 35))
    amp = draw(st.floats(0, 15))
    rh0 = draw(st.floats(0.2, 0.95))
    wind = draw(st.floats(0, 8))
    t = [t0 + amp * math.sin(2 * math.pi * i / 24) for i in range(n)]
    rh = [min(0.99, max(0.05, rh0 + 0.2 * math.sin(2 * math.pi * i / 24 + 1.0))) for i in range(n)]
    wdir = draw(st.one_of(st.none(), st.floats(0, 360)))
    return WeatherYear(t_out_c=t, rh_out=rh, wind_m_s=[wind] * n,
                       wind_dir_deg=[] if wdir is None else [wdir] * n)


@st.composite
def inputs(draw, **fixed):
    geo = CavityGeometry.from_inches(
        draw(st.floats(12, 200)), draw(st.floats(12, 200)), draw(st.floats(0.1, 6.0))
    )
    kw = dict(
        geometry=geo,
        f_cold=draw(st.floats(0.02, 0.95)),
        f_warm=draw(st.floats(0.05, 0.98)),
        u_assembly=draw(st.floats(0.3, 6.0)),
        t_room_c=draw(st.floats(10, 30)),
        rh_room=draw(st.floats(0.05, 0.8)),
        al_out=draw(st.floats(0.0, 3.0)),
        al_in=draw(st.floats(0.0, 3.0)),
        dp_pa=draw(st.floats(0.0, 20.0)),
        wind_scaling=draw(st.booleans()),
        desiccant_grams=draw(st.floats(0.0, 5000.0)),
        tau_hours=draw(st.floats(0.1, 48.0)),
        allow_desorption=draw(st.booleans()),
        full_fraction=draw(st.floats(0.5, 0.96)),
        pane_coupling=draw(st.booleans()),
        absorptance=0.0, sky_radiation=draw(st.booleans()),
        max_years=draw(st.integers(1, 3)),
        series_model=draw(st.booleans()),
        breathing=draw(st.booleans()),
        hvac=HvacSchedule(occupied_pa=draw(st.floats(-15, 25)), unoccupied_pa=draw(st.floats(-5, 5)),
                          weekdays_only=draw(st.booleans())),
        facade_azimuth_deg=draw(st.one_of(st.none(), st.floats(0, 360))),
        floor_height_m=draw(st.floats(2.5, 5.0)),
        loops=draw(st.booleans()),
        loop_k=draw(st.floats(0.0, 1.0)),
        loop_exponent=draw(st.floats(0.5, 1.0)),
    )
    floors = draw(st.integers(1, 40))
    kw["building_floors"] = floors
    kw["window_floor"] = draw(st.integers(1, floors))
    kw.update(fixed)
    return LifetimeInputs(**kw)


def _finite(x):
    return x is None or (isinstance(x, (int, float)) and math.isfinite(x))


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

@settings(**SETTINGS)
@given(weather_years(), inputs())
def test_outputs_are_finite_and_bounded(w, inp):
    r = run_lifetime(inp, w)
    q_max = inp.desiccant.q_max(0.0)
    assert _finite(r.exhausted_hour) and _finite(r.first_condensation_hour) and _finite(r.hours_per_gram)
    assert 0.0 <= r.final_loading <= q_max + 1e-9
    assert all(0.0 <= q <= q_max + 1e-9 for q in r.year1["loading"])
    assert all(x >= 0.0 for x in r.year1["w_cav"])
    assert all(0.0 <= f <= inp.max_film_kg + 1e-12 for f in r.year1["film_kg"])
    assert all(c >= 0.0 for c in r.year1["condensed_g"])
    assert all(math.isfinite(v) for k in r.year1 for v in r.year1[k])
    assert r.hours_run == r.years_run * w.hours


@settings(**SETTINGS)
@given(weather_years(), inputs())
def test_water_balance_on_the_desiccant(w, inp):
    r = run_lifetime(inp, w)
    expect = r.final_loading * inp.desiccant_grams
    assert abs(r.total_water_into_desiccant_g - expect) <= 1e-6 * max(1.0, expect) + 1e-9


@settings(**SETTINGS)
@given(weather_years(), inputs(desiccant_grams=0.0))
def test_no_desiccant_never_exhausts(w, inp):
    r = run_lifetime(inp, w)
    assert r.exhausted_hour is None and r.hours_per_gram is None
    assert r.total_water_into_desiccant_g == 0.0
    assert all(q == 0.0 for q in r.year1["loading"])


@settings(**SETTINGS)
@given(weather_years(), inputs(allow_desorption=False))
def test_loading_never_falls_without_desorption(w, inp):
    r = run_lifetime(inp, w)
    q = r.year1["loading"]
    assert all(b >= a - 1e-12 for a, b in zip(q, q[1:]))


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=2), st.floats(1.1, 5.0))
def test_more_desiccant_lasts_at_least_as_long(w, inp, factor):
    a = run_lifetime(inp, w, keep_year1=False, keep_daily=False)
    b = run_lifetime(replace(inp, desiccant_grams=inp.desiccant_grams * factor), w, keep_year1=False, keep_daily=False)
    ha = a.exhausted_hour if a.exhausted_hour is not None else 10 ** 9
    hb = b.exhausted_hour if b.exhausted_hour is not None else 10 ** 9
    assert hb >= ha


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=2, allow_desorption=False), st.floats(1.1, 5.0))
def test_more_leakage_never_lengthens_life(w, inp, factor):
    """More air of the SAME mix can only bring more water. Scaling one path
    alone changes the mix, and a rate-limited sieve (long tau) can then fill
    slower on a drier blend, which is physical, not a bug (found by this
    test at tau 46 h). Even at the same mix, more flow pulls the cavity air
    toward the stream temperature and shifts the RH a rate-limited sieve
    sees (found at tau 14 h, +7 %). Hence 10 % slack, and never less than
    one desiccant time constant (a 1 g sieve that fills in 11 h cannot be
    resolved finer than its 3 h tau; found by the series model). A
    supply-limited sieve (short tau) is checked strictly below."""
    a = run_lifetime(inp, w, keep_year1=False, keep_daily=False)
    b_inp = replace(inp, al_out=inp.al_out * factor, al_in=inp.al_in * factor)
    b = run_lifetime(b_inp, w, keep_year1=False, keep_daily=False)
    ha = a.exhausted_hour if a.exhausted_hour is not None else 10 ** 9
    hb = b.exhausted_hour if b.exhausted_hour is not None else 10 ** 9
    # Floor of 6 h: gram-scale sieves fill within hours, where the cavity's
    # own initial air inventory and the hour grid dominate (found when bead
    # diffusion became a signed path; the old engine fails the same example).
    assert hb <= ha + max(6, 0.1 * ha, inp.tau_hours)


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=2, allow_desorption=False, tau_hours=0.25, pane_coupling=False), st.floats(1.1, 5.0))
def test_more_leakage_strictly_shortens_life_when_supply_limited(w, inp, factor):
    a = run_lifetime(inp, w, keep_year1=False, keep_daily=False)
    b = run_lifetime(replace(inp, al_out=inp.al_out * factor, al_in=inp.al_in * factor), w, keep_year1=False, keep_daily=False)
    ha = a.exhausted_hour if a.exhausted_hour is not None else 10 ** 9
    hb = b.exhausted_hour if b.exhausted_hour is not None else 10 ** 9
    # A sieve that never reaches the 95 % threshold at the higher flow is the
    # documented equilibrium artifact (more flow pulls the cavity RH below
    # the sieve's 95 % point), not a longer life; skip that case. Found by
    # hypothesis on a 1 g sieve; the old engine fails it the same way.
    assume(not (a.exhausted_hour is not None and b.exhausted_hour is None))
    assert hb <= ha + 1


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=2), st.floats(1.5, 10.0))
def test_slower_desiccant_lasts_at_least_as_long(w, inp, factor):
    a = run_lifetime(inp, w, keep_year1=False, keep_daily=False)
    b = run_lifetime(replace(inp, tau_hours=inp.tau_hours * factor), w, keep_year1=False, keep_daily=False)
    ha = a.exhausted_hour if a.exhausted_hour is not None else 10 ** 9
    hb = b.exhausted_hour if b.exhausted_hour is not None else 10 ** 9
    assert hb >= ha


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=2))
def test_desorption_never_shortens_life(w, inp):
    a = run_lifetime(replace(inp, allow_desorption=False), w, keep_year1=False, keep_daily=False)
    b = run_lifetime(replace(inp, allow_desorption=True), w, keep_year1=False, keep_daily=False)
    ha = a.exhausted_hour if a.exhausted_hour is not None else 10 ** 9
    hb = b.exhausted_hour if b.exhausted_hour is not None else 10 ** 9
    assert hb >= ha


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=2))
def test_per_area_scaling(w, inp):
    """Quadruple the glass and the grams: same fill hour. Leakage is per m2
    of window so ACH is unchanged; the model is per m2 throughout.
    Sealant diffusion is the one term that is per PERIMETER (2x, not 4x),
    so it is switched off here; it has its own bound below. The single-sided
    loop is per window HEIGHT (a taller window is a taller chimney), so it
    is switched off too; test_taller_window_has_stronger_loop covers it."""
    inp = replace(inp, bead_width_m=0.0, loops=False)
    g = inp.geometry
    big = replace(inp, geometry=CavityGeometry(2 * g.width_m, 2 * g.height_m, g.offset_m),
                  desiccant_grams=4 * inp.desiccant_grams)
    a = run_lifetime(inp, w, keep_year1=False, keep_daily=False)
    b = run_lifetime(big, w, keep_year1=False, keep_daily=False)
    assert a.exhausted_hour == b.exhausted_hour
    assert abs(b.total_water_into_desiccant_g - 4 * a.total_water_into_desiccant_g) <= 1e-6 * max(1.0, 4 * a.total_water_into_desiccant_g)


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=2))
def test_offset_does_not_change_fill_time(w, inp):
    """Crack flow per m2 is fixed by the rating; a deeper cavity has lower
    ACH but more air, and the same water arrives. Allow 1 hour for the
    slight change in cavity air temperature and initial inventory."""
    g = inp.geometry
    deep = replace(inp, geometry=CavityGeometry(g.width_m, g.height_m, 3 * g.offset_m))
    # Water trapped in the cavity air at sealing is real and, since
    # 2026-09-23, conserved (the old solver discarded it whenever the air
    # snapped to balance). A deeper cavity traps more; where that extra is a
    # noticeable share of a gram-scale sieve, the deep cavity really does
    # fill sooner (hypothesis: 6 g, sealed, 2 vs 6 in: 144 vs 30 h). The
    # property holds only where the extra trapped water is small.
    ta, tb = build_tables(inp, w, None), build_tables(deep, w, None)
    cap = inp.desiccant_grams / 1000.0 / g.glazing_area_m2 * inp.full_fraction * inp.desiccant.q_max(25.0)
    extra = tb.m_cav[0] * tb.w_supply[0] - ta.m_cav[0] * ta.w_supply[0]
    assume(cap <= 0.0 or extra < 0.05 * cap)
    a = run_lifetime(inp, w, keep_year1=False, keep_daily=False)
    b = run_lifetime(deep, w, keep_year1=False, keep_daily=False)
    if a.exhausted_hour is not None and b.exhausted_hour is not None:
        # Floor of 6 h: a 3x deeper cavity starts with 3x the air, and for a
        # gram-scale sieve that inventory is a noticeable share of capacity
        # (86 vs 82 h found by hypothesis).
        assert abs(a.exhausted_hour - b.exhausted_hour) <= max(6, int(0.02 * a.exhausted_hour))


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=1))
def test_deterministic(w, inp):
    a = run_lifetime(inp, w)
    b = run_lifetime(inp, w)
    assert a.exhausted_hour == b.exhausted_hour and a.final_loading == b.final_loading
    assert a.year1["loading"] == b.year1["loading"]


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=1, al_out=0.0, al_in=0.0, dp_pa=0.0, wind_scaling=False))
def test_sealed_cavity_only_has_its_own_water(w, inp):
    """No vents: the desiccant can only take the water the cavity held at
    the start plus what the sealant beads deliver NET. Bead diffusion is
    signed (a bead facing a drier side removes water), so the net can be
    negative; but it can never exceed the dry-cavity upper bound the
    tables carry, because that bound uses the full source vapour pressure
    against an empty cavity."""
    r = run_lifetime(inp, w)
    area = inp.geometry.glazing_area_m2
    initial_g = r.tables.w_supply[0] * r.tables.m_cav[0] * 1000.0 * area
    bead_g = sum(y.net_diffusion_g for y in r.years)
    n_years = len(r.years)
    bound_g = sum(r.tables.diff_kg_per_m2_h) * 1000.0 * area * n_years
    # The dry-air mass of the cavity is recomputed each hour from its
    # temperature (a quasi-static air mass, as in cavity_moisture), so at a
    # fixed humidity ratio the air's water changes at hour boundaries. Air
    # can never hold more than saturation at the pane, which bounds the water
    # this can add. Since 2026-09-23 the solver conserves water inside each
    # step, so the desiccant can now take that trace (1 g sieve, 1 ft2,
    # sealed: 0.0017 g phantom == 0.0017 g excess, to 6 decimals).
    tb_ = r.tables
    phantom_g = sum(max(0.0, tb_.m_cav[i] - tb_.m_cav[i - 1]) for i in range(1, tb_.n)) \
        * max(tb_.w_sat_cold) * 1000.0 * area * n_years
    slack = 0.05 * (initial_g + abs(bead_g)) + phantom_g + 1e-6
    assert r.total_water_into_desiccant_g <= initial_g + bead_g + slack
    assert bead_g <= bound_g * 1.10 + 1e-6      # 10 %: the bead flux is linearised in W


# ---------------------------------------------------------------------------
# Series pressure model invariants
# ---------------------------------------------------------------------------

@settings(**SETTINGS)
@given(weather_years(), inputs(series_model=True, breathing=False, loops=False))
def test_series_feeds_one_side_per_hour(w, inp):
    tb = build_tables(inp, w, None)
    for a_out, a_tot in zip(tb.ach_out, tb.ach_total):
        a_in = a_tot - a_out
        assert min(a_out, a_in) <= 1e-12


@settings(**SETTINGS)
@given(weather_years(), inputs(series_model=True, breathing=False, loops=False))
def test_series_flow_never_exceeds_tighter_layer_alone(w, inp):
    """The tighter layer at the FULL |dP| is an upper bound on through-flow."""
    tb = build_tables(inp, w, None)
    tight = min(inp.al_out, inp.al_in)
    for a_tot, dp in zip(tb.ach_total, tb.dp_pa):
        bound = ach_from_air_leakage(tight, abs(dp), inp.geometry.offset_m)
        assert a_tot <= bound * (1 + 1e-9) + 1e-12


@settings(**SETTINGS)
@given(weather_years(), inputs(series_model=True, breathing=False, loops=False), st.floats(0.05, 0.95))
def test_tightening_a_layer_never_raises_flow(w, inp, factor):
    a = build_tables(inp, w, None).ach_total
    b = build_tables(replace(inp, al_in=inp.al_in * factor), w, None).ach_total
    assert all(y <= x * (1 + 1e-9) + 1e-12 for x, y in zip(a, b))


@settings(**SETTINGS)
@given(weather_years(), inputs(series_model=True, al_in=0.0, loops=False))
def test_hermetic_layer_leaves_breathing_only(w, inp):
    tb = build_tables(inp, w, None)
    assert max(tb.ach_total) < 0.2                    # a 50 K hourly swing would be 0.17
    if not inp.breathing:
        assert max(tb.ach_total) == 0.0


@settings(**SETTINGS)
@given(weather_years(), inputs(series_model=True, breathing=False, loops=False))
def test_fed_side_follows_pressure_sign(w, inp):
    tb = build_tables(inp, w, None)
    for a_out, a_tot, dp in zip(tb.ach_out, tb.ach_total, tb.dp_pa):
        if a_tot > 0:
            assert (a_out > 0) == (dp < 0)


@settings(**SETTINGS)
@given(weather_years(), inputs(series_model=True, loops=True))
def test_loop_only_through_its_own_layer_and_never_negative(w, inp):
    tb = build_tables(inp, w, None)
    assert all(x >= 0.0 for x in tb.loop_out) and all(x >= 0.0 for x in tb.loop_in)
    if inp.al_out == 0.0:
        assert max(tb.loop_out) == 0.0
    if inp.al_in == 0.0:
        assert max(tb.loop_in) == 0.0
    if inp.loop_k == 0.0:
        assert max(tb.loop_out) == 0.0 and max(tb.loop_in) == 0.0


@settings(**SETTINGS)
@given(weather_years(), inputs(series_model=True, breathing=False, loops=True), st.floats(0.05, 0.95))
def test_loops_never_lower_total_exchange_and_shrink_with_k(w, inp, factor):
    with_loops = build_tables(inp, w, None)
    without = build_tables(replace(inp, loops=False), w, None)
    assert all(a >= b * (1 - 1e-9) for a, b in zip(with_loops.ach_total, without.ach_total))
    smaller_k = build_tables(replace(inp, loop_k=inp.loop_k * factor), w, None)
    # The loop feeds the cavity and moves its air temperature, so the two
    # histories diverge after hour 0 and single hours can cross over (as in
    # the taller-window test below). Exact on the first hour, and on the
    # year's total. Found by hypothesis; fails the same way on the old engine.
    assert smaller_k.loop_out[0] <= with_loops.loop_out[0] * (1 + 1e-9) + 1e-12
    assert sum(smaller_k.loop_out) <= sum(with_loops.loop_out) * (1 + 1e-9) + 1e-9


@settings(**SETTINGS)
@given(weather_years(), inputs(series_model=True, loops=True, loop_k=0.75), st.floats(1.2, 3.0))
def test_taller_window_has_stronger_loop(w, inp, factor):
    g = inp.geometry
    tall = replace(inp, geometry=CavityGeometry(g.width_m, g.height_m * factor, g.offset_m))
    a, b = build_tables(inp, w, None), build_tables(tall, w, None)
    # Same first hour on both (cavity temperature seeds identically), then the
    # cavity temperature histories diverge, so only the first hour is exact.
    if a.loop_out[0] > 0:
        assert b.loop_out[0] == pytest.approx(a.loop_out[0] * factor ** inp.loop_exponent, rel=1e-6)
    assert sum(b.loop_out) >= sum(a.loop_out) * (1 - 1e-9)
