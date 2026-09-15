"""engine.pressure: signed dP components, series flow, breathing."""

import math

import pytest

from engine.leakage import ach_from_air_leakage, FLOW_EXPONENT
from engine.pressure import (
    HvacSchedule, breathing_ach, breathing_split, cp_from_angle, flow_coefficient,
    height_above_npl_m, hour_flow, pressure_split_pa, series_flow_m3h_m2, stack_dp_pa,
    wind_angle_off_normal_deg, wind_dp_pa,
)

N = FLOW_EXPONENT


# --- series flow -----------------------------------------------------------

def _series_by_bisection(al_out, al_in, dp, n=N):
    c_o, c_i = flow_coefficient(al_out, n), flow_coefficient(al_in, n)
    lo, hi = 0.0, dp
    for _ in range(200):
        x = 0.5 * (lo + hi)
        if c_o * x ** n > c_i * (dp - x) ** n:
            hi = x
        else:
            lo = x
    x = 0.5 * (lo + hi)
    return c_o * x ** n


@pytest.mark.parametrize("al_out,al_in,dp", [
    (0.005, 0.005, 5.0), (0.30, 0.005, 3.0), (2.0, 0.06, 12.0), (0.06, 2.0, 1.0),
])
def test_series_closed_form_matches_root_solve(al_out, al_in, dp):
    assert series_flow_m3h_m2(al_out, al_in, dp) == pytest.approx(
        _series_by_bisection(al_out, al_in, dp), rel=1e-9)


def test_equal_layers_each_take_half_the_pressure():
    x_out, x_in = pressure_split_pa(0.1, 0.1, 6.0)
    assert x_out == pytest.approx(3.0) and x_in == pytest.approx(3.0)
    q = series_flow_m3h_m2(0.1, 0.1, 6.0)
    assert q == pytest.approx(flow_coefficient(0.1) * 3.0 ** N)


def test_series_is_3x_below_parallel_sum_for_equal_layers():
    off = 0.01524
    parallel = 2 * ach_from_air_leakage(0.1, 6.0, off)
    series = series_flow_m3h_m2(0.1, 0.1, 6.0) / off
    assert parallel / series == pytest.approx(2 ** (1 + N), rel=1e-9)   # 3.14


def test_tight_layer_controls():
    # Retrofit 60x tighter than the existing window: flow within 3 % of the
    # retrofit alone at the full pressure, and the retrofit takes ~98 % of dP.
    q = series_flow_m3h_m2(0.30, 0.005, 3.0)
    q_tight_alone = flow_coefficient(0.005) * 3.0 ** N
    assert 0.97 < q / q_tight_alone < 1.0
    x_out, x_in = pressure_split_pa(0.30, 0.005, 3.0)
    assert x_in / 3.0 > 0.98


def test_series_symmetric_in_the_two_layers():
    assert series_flow_m3h_m2(0.3, 0.02, 4.0) == pytest.approx(series_flow_m3h_m2(0.02, 0.3, 4.0))


def test_series_monotonic_in_pressure_and_zero_at_zero():
    assert series_flow_m3h_m2(0.1, 0.1, 0.0) == 0.0
    qs = [series_flow_m3h_m2(0.1, 0.1, d) for d in (0.5, 1, 2, 4, 8)]
    assert all(a < b for a, b in zip(qs, qs[1:]))


def test_hermetic_either_side_blocks_flow():
    assert series_flow_m3h_m2(0.0, 2.0, 10.0) == 0.0
    assert series_flow_m3h_m2(2.0, 0.0, 10.0) == 0.0


# --- wind ------------------------------------------------------------------

def test_cp_table_endpoints_and_interpolation():
    assert cp_from_angle(0) == 0.60
    assert cp_from_angle(90) == -0.50
    assert cp_from_angle(180) == -0.30
    assert cp_from_angle(22.5) == pytest.approx(0.425)
    assert cp_from_angle(270) == -0.50        # symmetric about the normal
    assert cp_from_angle(-45) == 0.25


def test_wind_angle_off_normal():
    assert wind_angle_off_normal_deg(180, 180) == 0          # south wind, south facade
    assert wind_angle_off_normal_deg(0, 180) == 180          # north wind, south facade
    assert wind_angle_off_normal_deg(90, 180) == 90
    assert wind_angle_off_normal_deg(350, 10) == 20


def test_wind_sign_convention():
    # Windward raises outdoor pressure so dP = P_room - P_out goes negative.
    assert wind_dp_pa(4.0, 180, 180) == pytest.approx(-0.5 * 1.2 * 16 * 0.6)
    assert wind_dp_pa(4.0, 0, 180) > 0                     # leeward suction
    assert wind_dp_pa(4.0, None, 180) == wind_dp_pa(4.0, 180, 180)   # fallback windward
    assert wind_dp_pa(0.0, 180, 180) == 0.0


# --- stack -----------------------------------------------------------------

def test_stack_sign_and_magnitude():
    # Winter, above the NPL: room pressure higher (exfiltration), dP > 0.
    dp = stack_dp_pa(10.0, 20.0, 0.0)
    assert dp > 0
    assert dp == pytest.approx(101325 / 287.05 * (1 / 273.15 - 1 / 293.15) * 9.80665 * 10, rel=1e-6)
    assert 8.0 < dp < 9.0
    assert stack_dp_pa(-10.0, 20.0, 0.0) == pytest.approx(-dp)      # below the NPL
    assert stack_dp_pa(10.0, 20.0, 35.0) < 0                         # summer reverses
    assert stack_dp_pa(10.0, 20.0, 20.0) == 0.0


def test_height_above_npl():
    assert height_above_npl_m(5, 10, 3.6) == pytest.approx(-0.5 * 3.6)   # just below mid
    assert height_above_npl_m(1, 20, 3.6) == pytest.approx((0.5 - 10) * 3.6)
    assert height_above_npl_m(20, 20, 3.6) > 0
    with pytest.raises(ValueError):
        height_above_npl_m(11, 10, 3.6)


# --- schedule --------------------------------------------------------------

def test_hvac_schedule_defaults():
    s = HvacSchedule()
    assert s.dp_pa(0 * 24 + 9) == 5.0          # Monday 09:00
    assert s.dp_pa(0 * 24 + 3) == 0.0          # Monday 03:00
    assert s.dp_pa(0 * 24 + 19) == 0.0         # end hour exclusive
    assert s.dp_pa(5 * 24 + 12) == 0.0         # Saturday noon
    occ = sum(s.is_occupied(h) for h in range(8760))
    assert occ == pytest.approx(8760 * 5 / 7 * 12 / 24, rel=0.01)


def test_hvac_schedule_always_on():
    s = HvacSchedule(occupied_pa=12.0, start_h=0, end_h=24, weekdays_only=False)
    assert all(s.dp_pa(h) == 12.0 for h in range(0, 8760, 97))


# --- breathing -------------------------------------------------------------

def test_breathing_only_on_cooling():
    assert breathing_ach(20.0, 19.0) == pytest.approx(1 / 292.15)
    assert breathing_ach(19.0, 20.0) == 0.0
    assert breathing_split(0.3, 0.1) == pytest.approx((0.75, 0.25))
    assert breathing_split(0.0, 0.0) == (0.0, 0.0)


# --- hour_flow -------------------------------------------------------------

def test_hour_flow_feeds_one_side_only():
    common = dict(al_out=0.30, al_in=0.005, offset_m=0.01524, t_in_c=21.0, t_out_c=0.0,
                  wind_m_s=0.0, wind_from_deg=None, facade_azimuth_deg=180.0,
                  height_above_npl=0.0, hvac=HvacSchedule())
    occ = hour_flow(hour_of_year=9, **common)       # +5 Pa HVAC, room-fed
    assert occ.dp_pa == pytest.approx(5.0)
    assert occ.ach_out == 0.0 and occ.ach_in > 0
    assert occ.ach_in == pytest.approx(series_flow_m3h_m2(0.30, 0.005, 5.0) / 0.01524)
    calm_night = hour_flow(hour_of_year=3, **common)   # 0 Pa, no wind, no stack
    assert calm_night.ach_in == 0.0 and calm_night.ach_out == 0.0
    windy_night = hour_flow(hour_of_year=3, **{**common, "wind_m_s": 4.0, "wind_from_deg": 180.0})
    assert windy_night.dp_pa < 0 and windy_night.ach_out > 0 and windy_night.ach_in == 0.0


def test_hour_flow_breathing_is_two_sided():
    f = hour_flow(al_out=0.30, al_in=0.10, offset_m=0.01524, hour_of_year=3, t_in_c=21.0,
                  t_out_c=21.0, wind_m_s=0.0, wind_from_deg=None, facade_azimuth_deg=180.0,
                  height_above_npl=0.0, hvac=HvacSchedule(), breathing=0.004)
    assert f.dp_pa == 0.0
    assert f.ach_out == pytest.approx(0.003) and f.ach_in == pytest.approx(0.001)
