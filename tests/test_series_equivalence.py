"""Series model with a constant room-side pressure and no wind or stack must
reproduce the legacy engine fed with the same ACH on the room path only.
The moisture, desiccant and pane physics downstream are shared; this pins
that the rework changed only how the ACH and its side are decided."""

import gzip
from pathlib import Path

import pytest

from engine.geometry import CavityGeometry
from engine.lifetime import LifetimeInputs, build_tables, run_lifetime
from engine.pressure import HvacSchedule, series_flow_m3h_m2
from engine.weather import parse_nsrdb_csv

FIXTURE = Path(__file__).parent / "fixtures" / "nsrdb_277park_tmy_v4.csv.gz"


@pytest.fixture(scope="module")
def weather():
    y = parse_nsrdb_csv(gzip.open(FIXTURE, "rt").read())
    y.wind_m_s = [0.0] * y.hours          # kill wind so dP is HVAC only
    return y


def test_series_matches_legacy_room_path(weather):
    geo = CavityGeometry.from_inches(60, 96, 0.6)
    common = dict(geometry=geo, f_cold=0.30, f_warm=0.59, u_assembly=1.703,
                  desiccant_grams=200.0, absorptance=0.0, sky_radiation=False, max_years=2)
    ser = LifetimeInputs(al_out=0.30, al_in=0.02, series_model=True, breathing=False, loops=False,
                         hvac=HvacSchedule(occupied_pa=12.0, unoccupied_pa=12.0, start_h=0, end_h=24, weekdays_only=False),
                         # Window 0.5 mm below the neutral plane: stack is < 1e-3 Pa, i.e. off.
                         building_floors=2, window_floor=1, floor_height_m=0.001, t_room_c=21.0, **common)
    ach = series_flow_m3h_m2(0.30, 0.02, 12.0) / geo.offset_m
    leg = LifetimeInputs(ach_out=0.0, ach_in=ach, wind_scaling=False, series_model=False, t_room_c=21.0, **common)

    ts, tl = build_tables(ser, weather, None), build_tables(leg, weather, None)
    assert ts.dp_pa and all(abs(d - 12.0) < 2e-3 for d in ts.dp_pa)
    assert ts.ach_total == pytest.approx(tl.ach_total, rel=1e-4)
    assert ts.ach_out == pytest.approx(tl.ach_out, abs=1e-9)
    assert ts.w_supply == pytest.approx(tl.w_supply, rel=1e-4)

    rs, rl = run_lifetime(ser, weather, keep_year1=False, keep_daily=False), run_lifetime(leg, weather, keep_year1=False, keep_daily=False)
    assert rs.exhausted_hour == rl.exhausted_hour
    assert rs.total_water_into_desiccant_g == pytest.approx(rl.total_water_into_desiccant_g, rel=1e-4)
    assert rs.net_room_g == pytest.approx(rl.net_room_g, rel=1e-4)
    assert rs.net_outdoor_g == pytest.approx(rl.net_outdoor_g, abs=1e-9)
