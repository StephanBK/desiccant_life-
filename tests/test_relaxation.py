"""
Air relaxation in coupled_substep (2026-09-23).

The with-desiccant step used to put the cavity air at its balance humidity
W* instantly. Right while the desiccant is hungry (time constant of
seconds), wrong once it is full or tiny: then the air lags at the exchange
rate for hours, as in the no-desiccant step. The jump skipped the lead-in
before condensation, so after the desiccant filled the pane collected extra
water: 0.001 g gave 700 fog h/yr against 400 at 0 g, and a full 4 lb sieve
without desorption 745. These tests pin the fix.
"""

from __future__ import annotations

import gzip
import itertools
import time
from dataclasses import replace
from pathlib import Path

import pytest

import engine.lifetime as L
from engine.cavity import f_warm_estimate
from engine.desiccant import DESICCANTS
from engine.geometry import CavityGeometry
from engine import psychro

FIXTURE = Path(__file__).parent / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz"
MS3A = DESICCANTS["ms3a"]


@pytest.fixture(scope="module")
def weather():
    from engine.weather import parse_nsrdb_csv
    return parse_nsrdb_csv(gzip.open(FIXTURE, "rt").read())


@pytest.fixture
def park():
    """277 Park study setup: VIG, both layers wet-sealed, 70 F / 30 %."""
    u = psychro.u_ip_to_si(0.16)
    r = psychro.r_ip_to_si(0.97)
    return L.LifetimeInputs(
        geometry=CavityGeometry.from_inches(60, 96, 0.6), f_cold=0.014,
        f_warm=f_warm_estimate(0.014, r, u), u_assembly=u,
        t_room_c=psychro.f_to_c(70), rh_room=0.30, al_out=0.005, al_in=0.005,
        desiccant_grams=0.0, allow_desorption=False, absorptance=0.1,
        building_floors=50, window_floor=25, facade_azimuth_deg=0.0, max_years=2,
    )


def _year2(r):
    y = r.years[1]
    film = max(r.daily_film_max_kg[365:730])
    return y.hours_visible, y.condensed_kg_per_m2, film


def test_tiny_desiccant_behaves_like_none(park, weather):
    """0.001 g fills in hours and must then behave like no desiccant. Water
    and film are compared tightly; visible HOURS loosely, because the film
    creeps along the 5 um threshold for weeks (0.007 um/h), so a 2 % film
    difference moves the crossing by days."""
    h0, c0, f0 = _year2(L.run_lifetime(park, weather))
    h1, c1, f1 = _year2(L.run_lifetime(replace(park, desiccant_grams=0.001), weather, years_after_full=1))
    assert c1 == pytest.approx(c0, rel=0.02)
    assert f1 == pytest.approx(f0, rel=0.03)
    assert abs(h1 - h0) <= 0.12 * h0
    assert h1 < 1.2 * h0          # the bug gave +75 %


def test_full_desiccant_without_desorption_never_adds_fog(park, weather):
    """A full sieve that may not release water can only take water out of
    the cavity, so it cannot give more fog or condensate than none."""
    h0, c0, _ = _year2(L.run_lifetime(park, weather))
    r = L.run_lifetime(replace(park, desiccant_grams=1814.0, max_years=3), weather, years_after_full=1)
    assert r.exhausted_hour is not None
    y = r.years[-1]
    assert y.hours_visible <= h0
    assert y.condensed_kg_per_m2 <= c0 * 1.02


def test_hungry_desiccant_still_snaps_to_balance():
    """A fresh 4 lb sieve pulls the air to W* within the substep, exactly as
    the old quasi-steady step did."""
    m_cav, m_des = 0.0183, 1.814 / 3.72
    w_new, q, film, c, up, vn = L.coupled_substep(          # pane (0.008) can hold the air (0.006)
        0.006, 0.0, 0.0, 0.006, 0.008, 0.3, m_cav, m_des, MS3A, 10.0, 2.0, 0.25, False, 101325.0, 0.1)
    assert w_new < 1e-4           # driven nearly dry, as W* is
    assert up > 0.0 and c == 0.0


def test_denormal_film_does_not_stall():
    """A film of 6e-323 kg (a denormal: zero in physics, > 0 to the CPU) once
    made the loop evaporate it in ever smaller slices forever. State taken
    from the 8 lb desorption run where it happened."""
    t0 = time.perf_counter()
    out = L.coupled_substep(
        0.0026183353748015464, 0.20808509048093943, 6e-323, 0.0022053017946607107,
        0.0026183353748015464, 1.1981485475581475, 0.0183, 3.629 / 3.72, MS3A,
        -2.268826338203878, 2.0, 0.25, True, 101325.0, 0.1)
    assert time.perf_counter() - t0 < 0.5
    assert out[2] == 0.0


def test_every_substep_conserves_water():
    """Air + film + desiccant change equals what the vents and beads bring,
    to rounding, across wetting, drying, pinned and free regimes."""
    m_cav = 0.0183
    for w0, wsup, wsat, film, q, a, t_air, desorb, j in itertools.product(
        (0.001, 0.004, 0.008), (0.002, 0.006), (0.003, 0.005), (0.0, 2e-6, 5e-4),
        (0.0, 0.15, 0.205), (0.0, 0.3, 5.0), (-5.0, 20.0), (False, True), (0.0, 1e-6),
    ):
        m_des = 0.5
        w1, q1, f1, c, up, vn = L.coupled_substep(
            w0, q, film, wsup, wsat, a, m_cav, m_des, MS3A, t_air, 2.0, 0.25, desorb, 101325.0, 10.0, j)
        lhs = m_cav * (w1 - w0) + (f1 - film) + up
        rhs = vn + j * 0.25
        assert lhs == pytest.approx(rhs, abs=1e-12 + 1e-9 * max(abs(rhs), m_cav * w0)), (w0, wsup, wsat, film, q, a, t_air, desorb, j)
        assert w1 >= 0.0 and f1 >= 0.0 and q1 >= 0.0
        if not desorb:
            assert up >= -1e-15


def test_safety_net_unused_on_real_runs(park, weather):
    L.RELAX_STATS["safety_net"] = 0
    L.run_lifetime(replace(park, desiccant_grams=3629.0, allow_desorption=True, max_years=1), weather, years_after_full=1)
    L.run_lifetime(replace(park, desiccant_grams=0.5, al_out=1.0, al_in=0.3), weather, years_after_full=1)
    assert L.RELAX_STATS["safety_net"] == 0
