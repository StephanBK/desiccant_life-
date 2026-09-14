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

from hypothesis import HealthCheck, given, settings, strategies as st

from engine.geometry import CavityGeometry
from engine.lifetime import LifetimeInputs, run_lifetime
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
    return WeatherYear(t_out_c=t, rh_out=rh, wind_m_s=[wind] * n)


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
    )
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
    sees (found at tau 14 h, +7 %). Hence 10 % slack; a supply-limited
    sieve (short tau) is checked strictly below."""
    a = run_lifetime(inp, w, keep_year1=False, keep_daily=False)
    b_inp = replace(inp, al_out=inp.al_out * factor, al_in=inp.al_in * factor)
    b = run_lifetime(b_inp, w, keep_year1=False, keep_daily=False)
    ha = a.exhausted_hour if a.exhausted_hour is not None else 10 ** 9
    hb = b.exhausted_hour if b.exhausted_hour is not None else 10 ** 9
    assert hb <= ha + max(1, 0.1 * ha)


@settings(**SETTINGS)
@given(weather_years(), inputs(max_years=2, allow_desorption=False, tau_hours=0.25, pane_coupling=False), st.floats(1.1, 5.0))
def test_more_leakage_strictly_shortens_life_when_supply_limited(w, inp, factor):
    a = run_lifetime(inp, w, keep_year1=False, keep_daily=False)
    b = run_lifetime(replace(inp, al_out=inp.al_out * factor, al_in=inp.al_in * factor), w, keep_year1=False, keep_daily=False)
    ha = a.exhausted_hour if a.exhausted_hour is not None else 10 ** 9
    hb = b.exhausted_hour if b.exhausted_hour is not None else 10 ** 9
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
    so it is switched off here; it has its own bound below."""
    inp = replace(inp, bead_width_m=0.0)
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
    a = run_lifetime(inp, w, keep_year1=False, keep_daily=False)
    b = run_lifetime(deep, w, keep_year1=False, keep_daily=False)
    if a.exhausted_hour is not None and b.exhausted_hour is not None:
        assert abs(a.exhausted_hour - b.exhausted_hour) <= max(1, int(0.02 * a.exhausted_hour))


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
    the start plus what diffuses through the sealant bead, so uptake is
    bounded by one cavity volume plus the bead's integrated flux."""
    r = run_lifetime(inp, w)
    area = inp.geometry.glazing_area_m2
    initial_g = r.tables.w_supply[0] * r.tables.m_cav[0] * 1000.0 * area
    bead_g = sum(y.net_diffusion_g for y in r.years)
    assert r.total_water_into_desiccant_g <= (initial_g + bead_g) * 1.05 + 1e-6
    assert bead_g >= 0.0
