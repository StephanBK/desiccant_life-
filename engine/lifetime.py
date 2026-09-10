"""
Desiccant lifetime solver - the core of ANLY-003.

THE QUESTION
------------
Given a cavity of known size, a weather station, an outdoor leakage rate,
a room-side vent rate, room conditions and a mass of desiccant: how many
hours until the desiccant can take no more water, and how many hours until
the cold pane first fogs?

HOW IT RUNS
-----------
The TMY year is one weather year. Desiccant lifetime can be several, so the
year is played on repeat (up to ``max_years``) with the desiccant loading and
cavity humidity carried across the boundary. Everything that depends only on
weather and fixed inputs - cold-pane temperature, saturation ceiling, outdoor
humidity, cavity air mass, outdoor ACH after wind scaling - is computed ONCE
into 8,760-entry tables and reused every year. Only the state (W_cav, film,
loading) is stepped, which is what keeps a 20-year run under a second and a
2-D sweep under a minute.

THE HOUR, in order
------------------
  1. supply air:  W_sup = (a_out.W_out + a_in.W_room) / (a_out + a_in)
  2. exchange + condensation at the cold pane, closed form
     (engine.moisture.step_hour, unchanged physics)
  3. desiccant uptake toward its isotherm equilibrium at the cavity RH
  4. drain any film beyond the retained cap

Sub-stepping (default 4 per hour) keeps the split between 2 and 3 honest;
the desiccant time constant is hours, so 15-minute slices are well inside
its resolution.

END OF LIFE, two numbers
------------------------
  exhausted_hour        first hour with q >= full_fraction . q_max(25 degC).
                        The run continues to the end of that year so the
                        aftermath is on record.
                        A Langmuir sieve approaches full asymptotically, so
                        a fraction is unavoidable; 0.95 is the default and is
                        an input. What matters is that the desiccant's
                        equilibrium RH (rh_eq) is reported alongside, so you
                        can see it losing grip long before this hour.
  first_condensation_hour   first hour any water condenses on the cold pane.
                        The occupant-facing number.

SI throughout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from engine.cavity import (
    cavity_air_temperature,
    cavity_dry_air_mass,
    cloud_opacity,
    exterior_film_coefficient,
    radiative_surface_drop,
    solar_surface_boost,
    t_from_f,
    vent_cold_surface_rise_two_path,
)
from engine.desiccant import DESICCANTS, DEFAULT_DESICCANT, DesiccantType, uptake_step
from engine.geometry import CavityGeometry
from engine.moisture import (
    MAX_SURFACE_FILM_KG_PER_M2,
    VISIBLE_FILM_KG_PER_M2,
    drain_excess,
    step_hour,
)
from engine.psychro import (
    atmospheric_pressure_pa,
    dew_point_from_w,
    rh_from_t_w,
    w_from_t_rh,
    w_saturated,
)

# ---------------------------------------------------------------------------
# Presets for the two air paths. ESTIMATES - same caveat as engine.moisture.
# ---------------------------------------------------------------------------

#: Outdoor path: leakage through the EXISTING window into the cavity.
ACH_OUT_PRESETS: dict[str, float] = {
    "weathered": 20.0,
    "leaky": 5.0,
    "typical": 1.0,
    "tight": 0.2,
    "sealed": 0.02,
    "hermetic": 0.002,
}
ACH_OUT_LABELS: dict[str, str] = {
    "weathered": "Weathered - failed gaskets, open joints",
    "leaky": "Leaky - aged single-hung, no weatherstrip",
    "typical": "Typical - serviceable commercial window",
    "tight": "Tight - recently resealed",
    "sealed": "Sealed - new unit or wet-sealed perimeter",
    "hermetic": "Hermetic - IGU-grade edge seal (ESTIMATE)",
}

#: Room path: the SWR's own vent or perimeter leakage into the cavity.
ACH_IN_PRESETS: dict[str, float] = {
    "hermetic": 0.005,
    "sealed": 0.1,
    "tight_vent": 0.5,
    "moderate": 5.0,
    "open_vent": 20.0,
}
ACH_IN_LABELS: dict[str, str] = {
    "hermetic": "Hermetic - IGU-grade edge seal (ESTIMATE)",
    "sealed": "Sealed - gasketed perimeter, leakage only",
    "tight_vent": "Tight vent - small weep path",
    "moderate": "Moderate - designed baffle",
    "open_vent": "Open vent - deliberate vent slots",
}

#: Wind scaling of the OUTDOOR path. Infiltration through cracks goes as
#: dP^0.65 and wind pressure as v^2, so flow ~ v^1.3. A floor keeps the stack
#: and pressure-equalisation share alive at zero wind. Reference 4 m/s is a
#: typical NSRDB annual mean at 2 m. ESTIMATE.
WIND_REF_M_S = 4.0
WIND_EXPONENT = 1.3
WIND_FLOOR = 0.3


def wind_scaled_ach(ach_base: float, wind_m_s: float) -> float:
    """ACH through the existing window at this hour's wind speed. Equals
    ``ach_base`` at the reference wind, 0.3x in calm, 2.0x at 8 m/s."""
    if ach_base < 0:
        raise ValueError(f"ach_base cannot be negative, got {ach_base}")
    if wind_m_s < 0:
        wind_m_s = 0.0
    ratio = (wind_m_s / WIND_REF_M_S) ** WIND_EXPONENT
    return ach_base * (WIND_FLOOR + (1.0 - WIND_FLOOR) * ratio)


# ---------------------------------------------------------------------------
# Inputs and results
# ---------------------------------------------------------------------------

@dataclass
class LifetimeInputs:
    """Everything the solver needs. Built by the API from the request."""

    geometry: CavityGeometry
    f_cold: float
    f_warm: float
    u_assembly: float
    t_room_c: float = 21.0
    rh_room: float = 0.35
    ach_out: float = 1.0
    ach_in: float = 0.5
    wind_scaling: bool = True
    desiccant_grams: float = 50.0
    desiccant_key: str = DEFAULT_DESICCANT
    tau_hours: float | None = None
    allow_desorption: bool = False
    full_fraction: float = 0.95
    pane_coupling: bool = True
    absorptance: float = 0.10
    sky_radiation: bool = True
    max_years: int = 20
    substeps: int = 4
    max_film_kg: float = MAX_SURFACE_FILM_KG_PER_M2
    visible_film_kg: float = VISIBLE_FILM_KG_PER_M2

    def __post_init__(self) -> None:
        if not 0.0 <= self.f_cold <= 1.0:
            raise ValueError(f"f_cold must be in [0, 1], got {self.f_cold}")
        if not 0.0 <= self.f_warm <= 1.0:
            raise ValueError(f"f_warm must be in [0, 1], got {self.f_warm}")
        if self.u_assembly <= 0:
            raise ValueError("u_assembly must be positive")
        if not 0.0 <= self.rh_room <= 1.0:
            raise ValueError(f"rh_room must be in [0, 1], got {self.rh_room}")
        if self.ach_out < 0 or self.ach_in < 0:
            raise ValueError("ACH values cannot be negative")
        if self.desiccant_grams < 0:
            raise ValueError("desiccant_grams cannot be negative")
        if self.desiccant_key not in DESICCANTS:
            raise ValueError(f"Unknown desiccant {self.desiccant_key!r}")
        if not 0.0 < self.full_fraction <= 1.0:
            raise ValueError("full_fraction must be in (0, 1]")
        if self.max_years < 1 or self.max_years > 50:
            raise ValueError("max_years must be 1..50")
        if self.substeps < 1:
            raise ValueError("substeps must be at least 1")

    @property
    def desiccant(self) -> DesiccantType:
        return DESICCANTS[self.desiccant_key]

    @property
    def tau(self) -> float:
        return self.tau_hours if self.tau_hours is not None else self.desiccant.tau_hours


@dataclass
class HourTables:
    """Weather-driven, state-independent quantities for one TMY year.
    Computed once per run and reused every simulated year."""

    n: int
    t_out_c: list[float]
    w_out: list[float]
    t_cold_c: list[float]
    t_air_c: list[float]
    w_sat_cold: list[float]
    m_cav: list[float]
    ach_out: list[float]
    ach_total: list[float]
    w_supply: list[float]
    vent_rise_k: list[float]
    w_room: float


@dataclass
class YearSummary:
    year: int
    condensed_kg_per_m2: float
    hours_condensing: int
    hours_visible: int
    water_into_desiccant_g: float
    loading_end: float
    rh_eq_end: float
    mean_cavity_dew_point_c: float


@dataclass
class LifetimeResult:
    inputs: LifetimeInputs
    exhausted_hour: int | None
    first_condensation_hour: int | None
    years_run: int
    hours_run: int
    hours_per_gram: float | None
    final_loading: float
    final_rh_eq: float
    total_water_into_desiccant_g: float
    years: list[YearSummary]
    # Whole-run daily trace for the long chart: day index, loading, rh_eq,
    # cavity dew point, cold pane min. Length = days run.
    daily_loading: list[float] = field(default_factory=list)
    daily_rh_eq: list[float] = field(default_factory=list)
    daily_cav_dew_c: list[float] = field(default_factory=list)
    daily_pane_min_c: list[float] = field(default_factory=list)
    daily_film_max_kg: list[float] = field(default_factory=list)
    # First-year hourly trace for the animation.
    year1: dict[str, list[float]] = field(default_factory=dict)
    tables: HourTables | None = field(default=None, repr=False)

    @property
    def exhausted_years(self) -> float | None:
        return None if self.exhausted_hour is None else self.exhausted_hour / 8760.0

    @property
    def first_condensation_days(self) -> float | None:
        return None if self.first_condensation_hour is None else self.first_condensation_hour / 24.0


# ---------------------------------------------------------------------------
# Precompute
# ---------------------------------------------------------------------------

def build_tables(inp: LifetimeInputs, weather, poa_w_m2: list[float] | None) -> HourTables:
    """The 8,760-entry tables. ``weather`` is an engine.weather.WeatherYear."""
    n = weather.hours
    p_atm = atmospheric_pressure_pa(weather.elevation_m)
    gap = inp.geometry.offset_m
    w_room = w_from_t_rh(inp.t_room_c, inp.rh_room, p_atm_pa=p_atm)
    has_wind = bool(weather.wind_m_s)
    has_cloud = bool(weather.cloud_type)

    t_cold_l, t_air_l, w_sat_l, m_cav_l, w_out_l = [], [], [], [], []
    a_out_l, a_tot_l, w_sup_l, rise_l = [], [], [], []

    for i in range(n):
        t_o = weather.t_out_c[i]
        rh_o = min(max(weather.rh_out[i], 0.0), 1.0)
        wind = weather.wind_m_s[i] if has_wind else 2.0

        t_cold = t_from_f(inp.f_cold, t_out_c=t_o, t_in_c=inp.t_room_c)
        t_warm = t_from_f(inp.f_warm, t_out_c=t_o, t_in_c=inp.t_room_c)
        if poa_w_m2 is not None or inp.sky_radiation:
            h_out = exterior_film_coefficient(wind)
            if poa_w_m2 is not None and inp.absorptance > 0.0:
                t_cold += solar_surface_boost(poa_w_m2[i], inp.absorptance, h_out)
            if inp.sky_radiation:
                op = cloud_opacity(weather.cloud_type[i]) if has_cloud else 0.0
                t_cold += radiative_surface_drop(t_cold, t_o, h_out, opacity=op)

        a_out = wind_scaled_ach(inp.ach_out, wind) if inp.wind_scaling else inp.ach_out
        a_in = inp.ach_in
        a_tot = a_out + a_in

        rise = 0.0
        if inp.pane_coupling and a_tot > 0.0:
            rise = vent_cold_surface_rise_two_path(
                t_cold, inp.t_room_c, t_o, inp.f_cold, inp.u_assembly,
                a_in, a_out, gap_m=gap,
            )
            t_cold += rise

        # Cavity air: film-weighted mean of the two surfaces plus both
        # streams, each at its own temperature. Reuse the single-stream
        # function by feeding it the flow-weighted stream temperature.
        if a_tot > 0.0:
            t_stream = (a_out * t_o + a_in * inp.t_room_c) / a_tot
        else:
            t_stream = inp.t_room_c
        t_air = cavity_air_temperature(
            t_cold_c=t_cold, t_warm_c=t_warm, t_room_c=t_stream, ach=a_tot, gap_m=gap
        )

        w_out = w_from_t_rh(t_o, rh_o, p_atm_pa=p_atm) if rh_o > 0 else 0.0
        w_sup = (a_out * w_out + a_in * w_room) / a_tot if a_tot > 0 else w_room

        t_cold_l.append(t_cold); t_air_l.append(t_air)
        w_sat_l.append(w_saturated(t_cold, p_atm_pa=p_atm))
        m_cav_l.append(cavity_dry_air_mass(t_air, gap_m=gap, w=w_room, p_atm_pa=p_atm))
        w_out_l.append(w_out); a_out_l.append(a_out); a_tot_l.append(a_tot)
        w_sup_l.append(w_sup); rise_l.append(rise)

    return HourTables(
        n=n, t_out_c=list(weather.t_out_c), w_out=w_out_l, t_cold_c=t_cold_l,
        t_air_c=t_air_l, w_sat_cold=w_sat_l, m_cav=m_cav_l, ach_out=a_out_l,
        ach_total=a_tot_l, w_supply=w_sup_l, vent_rise_k=rise_l, w_room=w_room,
    )


# ---------------------------------------------------------------------------
# The solver
# ---------------------------------------------------------------------------

def run_lifetime(
    inp: LifetimeInputs,
    weather,
    poa_w_m2: list[float] | None = None,
    tables: HourTables | None = None,
    keep_year1: bool = True,
    keep_daily: bool = True,
) -> LifetimeResult:
    """Play the TMY year on repeat until the desiccant is exhausted or
    ``max_years`` is reached."""
    tb = tables if tables is not None else build_tables(inp, weather, poa_w_m2)
    n = tb.n
    des = inp.desiccant
    # Grams are per WINDOW; the moisture engine works per m2 of glass.
    area = inp.geometry.glazing_area_m2
    m_des = inp.desiccant_grams / 1000.0 / area          # kg desiccant per m2 of glass
    tau = inp.tau
    q_full = inp.full_fraction * des.q_max(25.0)
    p_atm = atmospheric_pressure_pa(weather.elevation_m)
    dt = 1.0 / inp.substeps

    # State
    w_cav = tb.w_supply[0]
    film = 0.0
    q = 0.0

    exhausted_hour: int | None = None
    first_cond_hour: int | None = None
    years: list[YearSummary] = []
    total_uptake = 0.0

    daily_q, daily_rh, daily_dp, daily_pane, daily_film = [], [], [], [], []
    year1: dict[str, list[float]] = {
        k: [] for k in (
            "t_out_c", "t_cold_c", "t_air_c", "w_cav", "rh_cav", "dew_cav_c",
            "film_kg", "loading", "rh_eq", "uptake_g", "condensed_g", "ach_out",
        )
    }

    hours_run = 0
    for year in range(inp.max_years):
        y_cond = 0.0; y_hc = 0; y_hv = 0; y_up = 0.0; y_dp = 0.0
        d_q = d_rh = d_dp = 0.0; d_pane = 1e9; d_film = 0.0; d_n = 0

        for i in range(n):
            w_sup = tb.w_supply[i]; w_sat = tb.w_sat_cold[i]
            m_cav = tb.m_cav[i]; a_tot = tb.ach_total[i]; t_air = tb.t_air_c[i]
            hour_cond = 0.0; hour_up = 0.0

            for _ in range(inp.substeps):
                w_cav, c, _e, film = step_hour(w_cav, w_sup, w_sat, a_tot, m_cav, film, dt)
                hour_cond += c
                if m_des > 0.0:
                    rh_cav = rh_from_t_w(t_air, w_cav, p_atm_pa=p_atm)
                    q_eq = des.q_eq(rh_cav, t_air)
                    q_new = uptake_step(q, q_eq, tau, dt, inp.allow_desorption)
                    dm = (q_new - q) * m_des                      # kg into desiccant
                    if dm > 0.0:
                        avail = w_cav * m_cav                      # cannot take more than the air holds
                        if dm > avail:
                            dm = avail
                            q_new = q + dm / m_des
                    w_cav = max(0.0, w_cav - dm / m_cav)
                    q = q_new
                    hour_up += dm
                film, _drained = drain_excess(film, inp.max_film_kg)

            hours_run += 1
            total_uptake += hour_up
            y_cond += hour_cond; y_up += hour_up
            if hour_cond > 0.0:
                y_hc += 1
                if first_cond_hour is None:
                    first_cond_hour = hours_run - 1
            if film > inp.visible_film_kg:
                y_hv += 1
            # Below ~1e-6 kg/kg (dew point near -75 degC) the solver has
            # nothing to solve; a fresh sieve gets there in hours.
            dp = dew_point_from_w(w_cav, p_atm_pa=p_atm) if w_cav > 1e-6 else -75.0
            y_dp += dp
            rh_eq = des.rh_eq(q, t_air) if m_des > 0 else 1.0

            if keep_year1 and year == 0:
                y1 = year1
                y1["t_out_c"].append(tb.t_out_c[i]); y1["t_cold_c"].append(tb.t_cold_c[i])
                y1["t_air_c"].append(t_air); y1["w_cav"].append(w_cav)
                y1["rh_cav"].append(rh_from_t_w(t_air, w_cav, p_atm_pa=p_atm))
                y1["dew_cav_c"].append(dp); y1["film_kg"].append(film)
                y1["loading"].append(q); y1["rh_eq"].append(rh_eq)
                y1["uptake_g"].append(hour_up * 1000.0 * area); y1["condensed_g"].append(hour_cond * 1000.0 * area)
                y1["ach_out"].append(tb.ach_out[i])

            if keep_daily:
                d_q += q; d_rh += rh_eq; d_dp += dp; d_n += 1
                d_pane = min(d_pane, tb.t_cold_c[i]); d_film = max(d_film, film)
                if d_n == 24:
                    daily_q.append(d_q / 24); daily_rh.append(d_rh / 24)
                    daily_dp.append(d_dp / 24); daily_pane.append(d_pane); daily_film.append(d_film)
                    d_q = d_rh = d_dp = 0.0; d_pane = 1e9; d_film = 0.0; d_n = 0

            if exhausted_hour is None and m_des > 0.0 and q >= q_full:
                exhausted_hour = hours_run

        years.append(YearSummary(
            year=year + 1, condensed_kg_per_m2=y_cond, hours_condensing=y_hc,
            hours_visible=y_hv, water_into_desiccant_g=y_up * 1000.0 * area,
            loading_end=q, rh_eq_end=des.rh_eq(q, 21.0) if m_des > 0 else 1.0,
            mean_cavity_dew_point_c=y_dp / n,
        ))
        # Finish the year exhaustion falls in, so first condensation and
        # the animation show the aftermath, then stop.
        if exhausted_hour is not None:
            break

    hpg = None
    if exhausted_hour is not None and inp.desiccant_grams > 0:
        hpg = exhausted_hour / inp.desiccant_grams

    return LifetimeResult(
        inputs=inp, exhausted_hour=exhausted_hour, first_condensation_hour=first_cond_hour,
        years_run=len(years), hours_run=hours_run, hours_per_gram=hpg,
        final_loading=q, final_rh_eq=des.rh_eq(q, 21.0) if m_des > 0 else 1.0,
        total_water_into_desiccant_g=total_uptake * 1000.0 * area, years=years,
        daily_loading=daily_q, daily_rh_eq=daily_rh, daily_cav_dew_c=daily_dp,
        daily_pane_min_c=daily_pane, daily_film_max_kg=daily_film,
        year1=year1 if keep_year1 else {}, tables=tb,
    )
