"""
Signed room-to-outdoor pressure, series flow through the two layers, and
what side the cavity is fed from.

WHY THIS MODULE (Sep 15 2026 rework)
------------------------------------
The first version of the solver treated the existing window and the retrofit
as two INDEPENDENT leaks, each at the same operating pressure, both feeding
the cavity every hour ("parallel"). A two-layer assembly does not work that
way. There is one pressure difference between room and outdoors; the cavity
floats to a pressure in between; the same air passes through both layers in
series; and the cavity is fed from whichever side is at the higher pressure
that hour. The tighter layer takes most of the pressure and sets the flow.

SIGN CONVENTION
---------------
    dP = P_room - P_outdoor   at the window        [Pa]

    dP > 0  room pushes air through the retrofit into the cavity and out
            through the existing window: the cavity is ROOM-fed
    dP < 0  outdoor air comes in through the existing window and leaves
            through the retrofit: the cavity is OUTDOOR-fed

THE THREE COMPONENTS
--------------------
1. HVAC pressurisation, a building operations setpoint. Design guidance puts
   the range at 5 to 25 Pa with 12.5 Pa (0.05 in wc) as the ideal; field
   measurements in existing buildings find 1 to 2 Pa, fluctuating, and often
   negative when exhaust exceeds intake. Old facades with leaky operable
   windows cannot be held near the setpoint. Night setback closes the
   outdoor damper and pressurisation falls to about zero. Defaults:
   +5 Pa occupied (weekdays 07:00 to 19:00), 0 Pa unoccupied. ESTIMATE.

2. Stack. Indoor air warmer than outdoor is lighter, so indoor pressure
   falls more slowly with height than outdoor pressure. Above the neutral
   pressure plane (NPL) indoor pressure exceeds outdoor (exfiltration),
   below it the reverse:

       dP_stack = (rho_out - rho_in) . g . h          h > 0 above the NPL
       rho      = p / (R_air . T)

   With uniform leakage over the height the NPL sits at mid-height, so
   h = (floor - floors / 2) x floor height. A ground-floor window in a
   20-storey building in winter sees about -8 Pa; the 5th floor of a
   10-storey building about zero.

3. Wind. Stagnation pressure on the outdoor face, 0.5 rho v^2 Cp, where Cp
   depends on the angle between the wind and the facade normal. Positive
   Cp (windward) raises outdoor pressure, i.e. lowers dP:

       dP_wind = -0.5 . rho . v^2 . Cp(theta)

   Cp table (face-averaged values for a rectangular building, ASHRAE
   Fundamentals, airflow around buildings; ESTIMATE):
       theta   0     45     90    135    180   degrees off the normal
       Cp     +0.60 +0.25  -0.50  -0.40  -0.30
   Side walls (90 deg) are in suction, not neutral. Wind speed and direction
   come from the weather station (10 m, open terrain); no height or terrain
   correction is applied, which overstates wind on low floors in dense
   urban settings and understates it high on a tower.

SERIES FLOW
-----------
Each layer follows the crack-flow power law q = C . dP^n with the same n.
The cavity pressure x (as a drop across the outdoor layer) satisfies

    C_out . x^n = C_in . (|dP| - x)^n

which has the closed form

    q_series = |dP|^n / (C_out^(-1/n) + C_in^(-1/n))^n

The tighter layer dominates the denominator. When the two are equal each
takes half the pressure and q = C . (|dP|/2)^n, 3.1x less than the sum of
the two independent flows at full dP for n = 0.65. When one layer is 60x
tighter (wet-sealed retrofit over an operable window) q is within 3 % of
the tight layer alone at the full dP.

SINGLE-SIDED LOOPS (added the same day, after review)
--------------------------------------------------------
Series through-flow is not the only exchange. Each layer also trades air
with the side it faces THROUGH ITS OWN CRACKS, with nothing passing the
other layer: a small chimney. The cavity air is warmer or colder than the
side beyond the layer, the layer has cracks low and high (sill and head
on an operable sash), so air of one density leaves at one end and air of
the other density comes in at the other end. Driving pressure

    dP_loop = |rho_side - rho_cavity| . g . k . H_window

k is the fraction of the window height separating the average inlet from
the average outlet: 1 with all leakage at head and sill, 0.5 spread
evenly, 0 all at one height. Default 0.75, ESTIMATE. Half the layer's
leakage is the inlet, half the outlet, each at dP_loop / 2:

    q_loop = (C / 2) . (dP_loop / 2)^n_loop        n_loop default 0.65

At well under 1 Pa crack flow is probably laminar (n near 1), which
would give up to 6x less; 0.65 is kept as the conservative choice for
desiccant life and is a parameter. Gust pumping and the wind-pressure
gradient over the face drive the same kind of loop and are not modelled;
they are second order next to the buoyant loop.

Consequence: with a hermetic retrofit the cavity still breathes outdoor
air through the old window at its own rate, so BOTH seals matter: the
tighter layer sets the through-flow, each layer's own leakage sets its
loop. This is why interior storm windows fog over leaky prime windows,
and why INOVUES wet-seals both sides.

BREATHING
---------
The only exchange that is genuinely two-sided. Cavity air expands and
contracts with temperature; the volume fraction exchanged per hour is
|dT| / T. Air is drawn IN only while the cavity cools, and it is drawn from
both sides in proportion to their flow coefficients. About 0.003 ACH for
a 1 K hourly change, negligible against crack flow unless both layers are
at the detection floor, where it is the floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engine.leakage import CFM_FT2_TO_M3H_M2, FLOW_EXPONENT, RHO_AIR, TEST_PRESSURE_PA

G = 9.80665
R_AIR = 287.05          # J/(kg K), dry air

#: Face-averaged pressure coefficient vs angle between wind and facade
#: normal, degrees. ESTIMATE, see module docstring.
CP_TABLE: tuple[tuple[float, float], ...] = (
    (0.0, 0.60), (45.0, 0.25), (90.0, -0.50), (135.0, -0.40), (180.0, -0.30),
)
#: Used when the weather file has no wind direction: the old windward
#: assumption, which is the conservative choice for outdoor-air ingress.
CP_FALLBACK = 0.60

DEFAULT_P_OCCUPIED_PA = 5.0
DEFAULT_P_UNOCCUPIED_PA = 0.0
DEFAULT_OCC_START_H = 7
DEFAULT_OCC_END_H = 19
DEFAULT_FLOORS = 10
DEFAULT_WINDOW_FLOOR = 5
DEFAULT_FLOOR_HEIGHT_M = 3.6
DEFAULT_LOOP_K = 0.75
DEFAULT_LOOP_EXPONENT = FLOW_EXPONENT


# ---------------------------------------------------------------------------
# Pressure coefficient and wind
# ---------------------------------------------------------------------------

def cp_from_angle(theta_deg: float) -> float:
    """Face-averaged Cp for a wind ``theta_deg`` off the facade normal."""
    t = abs(theta_deg) % 360.0
    if t > 180.0:
        t = 360.0 - t
    for (a0, c0), (a1, c1) in zip(CP_TABLE, CP_TABLE[1:]):
        if a0 <= t <= a1:
            return c0 + (c1 - c0) * (t - a0) / (a1 - a0)
    return CP_TABLE[-1][1]


def wind_angle_off_normal_deg(wind_from_deg: float, facade_azimuth_deg: float) -> float:
    """Angle between the wind vector and the facade outward normal.

    Both bearings are clockwise from north; ``wind_from_deg`` is the
    direction the wind blows FROM (met convention). A wind FROM the south
    (180) hits a south-facing facade (azimuth 180) head on: angle 0.
    """
    d = (wind_from_deg - facade_azimuth_deg) % 360.0
    return 360.0 - d if d > 180.0 else d


def wind_dp_pa(wind_m_s: float, wind_from_deg: float | None,
               facade_azimuth_deg: float | None, rho: float = RHO_AIR) -> float:
    """Contribution of wind to dP = P_room - P_outdoor (so windward is negative)."""
    if wind_m_s < 0:
        wind_m_s = 0.0
    if wind_from_deg is None or facade_azimuth_deg is None:
        cp = CP_FALLBACK
    else:
        cp = cp_from_angle(wind_angle_off_normal_deg(wind_from_deg, facade_azimuth_deg))
    return -0.5 * rho * wind_m_s ** 2 * cp


# ---------------------------------------------------------------------------
# Stack
# ---------------------------------------------------------------------------

def air_density(t_c: float, p_pa: float) -> float:
    return p_pa / (R_AIR * (t_c + 273.15))


def stack_dp_pa(height_above_npl_m: float, t_in_c: float, t_out_c: float,
                p_atm_pa: float = 101325.0) -> float:
    """dP = P_room - P_outdoor from buoyancy at ``height_above_npl_m``."""
    return (air_density(t_out_c, p_atm_pa) - air_density(t_in_c, p_atm_pa)) * G * height_above_npl_m


def height_above_npl_m(window_floor: int, floors: int, floor_height_m: float) -> float:
    """Neutral plane at mid-height (uniform leakage). Floor 1 is the ground
    floor; the window sits at the middle of its floor."""
    if floors < 1 or window_floor < 1 or window_floor > floors:
        raise ValueError(f"window floor {window_floor} must be within 1..{floors}")
    if floor_height_m <= 0:
        raise ValueError("floor height must be positive")
    return (window_floor - 0.5 - floors / 2.0) * floor_height_m


# ---------------------------------------------------------------------------
# HVAC schedule
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HvacSchedule:
    occupied_pa: float = DEFAULT_P_OCCUPIED_PA
    unoccupied_pa: float = DEFAULT_P_UNOCCUPIED_PA
    start_h: int = DEFAULT_OCC_START_H       # first occupied hour (inclusive)
    end_h: int = DEFAULT_OCC_END_H           # first unoccupied hour (exclusive)
    weekdays_only: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.start_h <= 24 or not 0 <= self.end_h <= 24:
            raise ValueError("schedule hours must be within 0..24")
        if abs(self.occupied_pa) > 75 or abs(self.unoccupied_pa) > 75:
            raise ValueError("HVAC pressurisation beyond +/-75 Pa is not a building")

    def is_occupied(self, hour_of_year: int) -> bool:
        """A TMY has no real calendar (each month is spliced from a different
        year), so weekdays are counted from a synthetic calendar that starts
        on a Monday. The share of occupied hours is what matters, not which
        dates they fall on."""
        if self.weekdays_only and (hour_of_year // 24) % 7 >= 5:
            return False
        h = hour_of_year % 24
        if self.start_h <= self.end_h:
            return self.start_h <= h < self.end_h
        return h >= self.start_h or h < self.end_h

    def dp_pa(self, hour_of_year: int) -> float:
        return self.occupied_pa if self.is_occupied(hour_of_year) else self.unoccupied_pa


# ---------------------------------------------------------------------------
# Series flow through the two layers
# ---------------------------------------------------------------------------

def flow_coefficient(al_cfm_ft2: float, exponent: float = FLOW_EXPONENT) -> float:
    """C in m3/h per m2 of window per Pa^n, from a 75 Pa rating."""
    if al_cfm_ft2 < 0:
        raise ValueError("air leakage cannot be negative")
    return al_cfm_ft2 * CFM_FT2_TO_M3H_M2 / TEST_PRESSURE_PA ** exponent


def series_flow_m3h_m2(al_out_cfm_ft2: float, al_in_cfm_ft2: float, dp_abs_pa: float,
                       exponent: float = FLOW_EXPONENT) -> float:
    """Through-flow per m2 of window for a two-layer assembly at |dP|."""
    if dp_abs_pa < 0:
        raise ValueError("pass |dP|")
    c_out = flow_coefficient(al_out_cfm_ft2, exponent)
    c_in = flow_coefficient(al_in_cfm_ft2, exponent)
    if c_out <= 0.0 or c_in <= 0.0 or dp_abs_pa == 0.0:
        return 0.0
    # Ratio form of |dP|^n / (C_out^(-1/n) + C_in^(-1/n))^n: the tight
    # layer's flow at full |dP|, reduced by the share of pressure the loose
    # layer takes. (tight/loose)^(1/n) <= 1, so nothing can overflow.
    c_tight, c_loose = min(c_out, c_in), max(c_out, c_in)
    share = (c_tight / c_loose) ** (1.0 / exponent)
    return c_tight * dp_abs_pa ** exponent / (1.0 + share) ** exponent


def pressure_split_pa(al_out_cfm_ft2: float, al_in_cfm_ft2: float, dp_abs_pa: float,
                      exponent: float = FLOW_EXPONENT) -> tuple[float, float]:
    """(drop across the existing window, drop across the retrofit)."""
    c_out = flow_coefficient(al_out_cfm_ft2, exponent)
    c_in = flow_coefficient(al_in_cfm_ft2, exponent)
    if c_out <= 0.0 and c_in <= 0.0:
        return dp_abs_pa / 2.0, dp_abs_pa / 2.0
    if c_out <= 0.0:
        return dp_abs_pa, 0.0
    if c_in <= 0.0:
        return 0.0, dp_abs_pa
    r = (c_in / c_out) ** (1.0 / exponent)     # x / (dP - x)
    x_out = dp_abs_pa * r / (1.0 + r)
    return x_out, dp_abs_pa - x_out


# ---------------------------------------------------------------------------
# Single-sided buoyant loop through one layer
# ---------------------------------------------------------------------------

def loop_dp_pa(t_side_c: float, t_cavity_c: float, window_height_m: float, k: float,
               p_atm_pa: float = 101325.0) -> float:
    """Chimney pressure of a loop through one layer, Pa (always >= 0)."""
    if not 0.0 <= k <= 1.0:
        raise ValueError("loop k must be within 0..1")
    if window_height_m < 0:
        raise ValueError("window height cannot be negative")
    return abs(air_density(t_side_c, p_atm_pa) - air_density(t_cavity_c, p_atm_pa)) * G * k * window_height_m


def loop_ach(al_cfm_ft2: float, offset_m: float, dp_loop_pa: float,
             exponent: float = DEFAULT_LOOP_EXPONENT) -> float:
    """Air exchanged with the side beyond one layer through that layer alone.
    Half the layer's leakage is the inlet and half the outlet, each across
    half the loop pressure; what enters equals what leaves."""
    if offset_m <= 0:
        raise ValueError("offset must be positive")
    if dp_loop_pa <= 0.0 or al_cfm_ft2 <= 0.0:
        return 0.0
    c_half = flow_coefficient(al_cfm_ft2, exponent) / 2.0
    return c_half * (dp_loop_pa / 2.0) ** exponent / offset_m


# ---------------------------------------------------------------------------
# Breathing
# ---------------------------------------------------------------------------

def breathing_ach(t_air_prev_c: float, t_air_now_c: float) -> float:
    """Cavity volume fraction drawn in this hour by contraction; zero while
    the cavity warms (it exhales)."""
    dt = t_air_prev_c - t_air_now_c
    if dt <= 0.0:
        return 0.0
    return dt / (t_air_now_c + 273.15)


def breathing_split(al_out_cfm_ft2: float, al_in_cfm_ft2: float) -> tuple[float, float]:
    """Share of breathed-in air from (outdoor, room), by flow coefficient."""
    s = al_out_cfm_ft2 + al_in_cfm_ft2
    if s <= 0.0:
        return 0.0, 0.0
    return al_out_cfm_ft2 / s, al_in_cfm_ft2 / s


# ---------------------------------------------------------------------------
# One hour, assembled
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HourFlow:
    dp_pa: float            # signed, P_room - P_outdoor
    dp_hvac_pa: float
    dp_stack_pa: float
    dp_wind_pa: float
    ach_out: float          # outdoor air into the cavity this hour (through-flow + loop + breathing share)
    ach_in: float           # room air into the cavity this hour
    loop_out: float = 0.0   # of which, the single-sided loop through the existing window
    loop_in: float = 0.0    # of which, the single-sided loop through the retrofit


def hour_flow(*, al_out: float, al_in: float, offset_m: float, hour_of_year: int,
              t_in_c: float, t_out_c: float, wind_m_s: float, wind_from_deg: float | None,
              facade_azimuth_deg: float | None, height_above_npl: float,
              hvac: HvacSchedule, p_atm_pa: float = 101325.0,
              exponent: float = FLOW_EXPONENT, breathing: float = 0.0,
              t_cavity_c: float | None = None, window_height_m: float = 0.0,
              loop_k: float = DEFAULT_LOOP_K, loop_exponent: float = DEFAULT_LOOP_EXPONENT) -> HourFlow:
    """Signed dP and the resulting one-sided through-flow, plus the two
    single-sided loops (when ``t_cavity_c`` is given) and breathing."""
    if offset_m <= 0:
        raise ValueError("offset must be positive")
    dp_h = hvac.dp_pa(hour_of_year)
    dp_s = stack_dp_pa(height_above_npl, t_in_c, t_out_c, p_atm_pa)
    dp_w = wind_dp_pa(wind_m_s, wind_from_deg, facade_azimuth_deg)
    dp = dp_h + dp_s + dp_w
    q = series_flow_m3h_m2(al_out, al_in, abs(dp), exponent)
    ach = q / offset_m
    a_out, a_in = (0.0, ach) if dp > 0.0 else (ach, 0.0)
    l_out = l_in = 0.0
    if t_cavity_c is not None and window_height_m > 0.0:
        l_out = loop_ach(al_out, offset_m, loop_dp_pa(t_out_c, t_cavity_c, window_height_m, loop_k, p_atm_pa), loop_exponent)
        l_in = loop_ach(al_in, offset_m, loop_dp_pa(t_in_c, t_cavity_c, window_height_m, loop_k, p_atm_pa), loop_exponent)
        a_out += l_out
        a_in += l_in
    if breathing > 0.0:
        f_out, f_in = breathing_split(al_out, al_in)
        a_out += breathing * f_out
        a_in += breathing * f_in
    return HourFlow(dp, dp_h, dp_s, dp_w, a_out, a_in, l_out, l_in)
