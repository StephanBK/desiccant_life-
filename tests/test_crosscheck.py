"""
Engine vs independent reference model. The reference (tests/reference_model.py)
is implicit Euler at fine steps with its own psychrometrics; the engine is a
quasi-steady coupled step with closed forms. They must agree on fill time
to a few percent. Four scenarios chosen for speed; the full 13-scenario
matrix (AUDIT.md, section 2) is run by hand when the physics changes.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from engine.geometry import CavityGeometry
from engine.lifetime import LifetimeInputs, run_lifetime
from reference_model import Sieve, run_reference

FIXTURE = Path(__file__).parent / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz"


@pytest.fixture(scope="module")
def weather():
    from engine.weather import parse_nsrdb_csv
    return parse_nsrdb_csv(gzip.open(FIXTURE, "rt").read())


GEO = CavityGeometry.from_inches(60, 96, 0.6024)

CASES = [
    # name, ach_out, ach_in, grams, tau, desorb, tolerance on fill hour
    ("moderate", 1.0, 0.5, 50, 2.0, False, 0.03),
    ("aerc_default", 14.75, 8.85, 50, 2.0, False, 0.05),
    ("sealed", 0.02, 0.1, 50, 2.0, False, 0.04),
    ("desorb", 0.5, 0.5, 200, 2.0, True, 0.03),
]


@pytest.mark.parametrize("name,a_out,a_in,grams,tau,desorb,tol", CASES)
def test_fill_time_matches_reference(weather, name, a_out, a_in, grams, tau, desorb, tol):
    inp = LifetimeInputs(
        geometry=GEO, f_cold=0.30, f_warm=0.59, u_assembly=1.703,
        absorptance=0.0, sky_radiation=False, pane_coupling=False, wind_scaling=False,
        ach_out=a_out, ach_in=a_in, desiccant_grams=grams, tau_hours=tau,
        allow_desorption=desorb, max_years=1,
        # The reference has no sealant vapour diffusion; compare like with
        # like (2026-09-23). With diffusion on, the 'sealed' case passed
        # only because two errors cancelled: +2.5 % from the old solver
        # dropping the cavity air's own water, -5 % from diffusion.
        sealant_out="none", sealant_in="none",
    )
    eng = run_lifetime(inp, weather, None, keep_year1=False, keep_daily=False)
    ref = run_reference(
        weather.t_out_c, weather.rh_out, 0.30, 0.59, inp.t_room_c, inp.rh_room,
        a_out, a_in, GEO.offset_m, grams / GEO.glazing_area_m2,
        sieve=Sieve(tau_h=tau), allow_desorption=desorb, max_years=1,
    )
    assert eng.exhausted_hour is not None and ref.exhausted_hour is not None
    assert abs(eng.exhausted_hour - ref.exhausted_hour) <= max(1, tol * ref.exhausted_hour), (name, eng.exhausted_hour, ref.exhausted_hour)


def test_hand_calculation_supply_limited(weather):
    """500 g at ~24 ACH: capacity 100 g, supply ~5 g/h -> ~20 h. The old split
    scheme said 98 h; this pins the fix."""
    inp = LifetimeInputs(
        geometry=GEO, f_cold=0.30, f_warm=0.59, u_assembly=1.703,
        absorptance=0.0, sky_radiation=False, pane_coupling=False, wind_scaling=False,
        ach_out=14.75, ach_in=8.85, desiccant_grams=500, max_years=1,
    )
    r = run_lifetime(inp, weather, None, keep_year1=False, keep_daily=False)
    assert 12 <= r.exhausted_hour <= 24
