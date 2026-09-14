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

Steps 2 and 3 are solved TOGETHER (coupled_substep): the cavity air is a
fast variable in quasi-equilibrium between vent supply and desiccant
uptake, and the pane condenses only if that equilibrium humidity exceeds
saturation. Sub-steps (default 4 per hour, more if the desiccant time
constant is short) only need to resolve the desiccant's own dynamics.
Without desiccant the engine's closed-form step_hour is used unchanged.

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
from engine.leakage import (
    DEFAULT_BEAD_DEPTH_M, DEFAULT_BEAD_WIDTH_M, DEFAULT_OPERATING_PA, DEFAULT_SEALANT, SEALANTS,
    ach_from_air_leakage, sealant_diffusion_kg_per_h, wind_pressure_pa,
)
from engine.moisture import (
    MAX_SURFACE_FILM_KG_PER_M2,
    VISIBLE_FILM_KG_PER_M2,
    drain_excess,
    step_hour,
)
from engine.psychro import (
    atmospheric_pressure_pa,
    dew_point_from_w,
    p_w_from_w,
    rh_from_t_w,
    w_from_t_rh,
    w_saturated,
)

# ---------------------------------------------------------------------------
# Presets for the two air paths. ESTIMATES - same caveat as engine.moisture.
# ---------------------------------------------------------------------------

#: Outdoor path: leakage through the EXISTING window into the cavity.
ACH_OUT_PRESETS: dict[str, float] = {
    "hermetic": 0.002,
    "sealed": 0.02,
    "tight": 0.2,
    "typical": 1.0,
    "leaky": 5.0,
    "weathered": 20.0,
}
ACH_OUT_LABELS: dict[str, str] = {
    "hermetic": "Hermetic - IGU-grade edge seal (ESTIMATE)",
    "sealed": "Sealed - new unit or wet-sealed perimeter",
    "tight": "Tight - recently resealed",
    "typical": "Typical - serviceable commercial window",
    "leaky": "Leaky - aged single-hung, no weatherstrip",
    "weathered": "Weathered - failed gaskets, open joints",
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

#: LEGACY wind scaling of the OUTDOOR path, used only when leakage is given
#: as a bare ACH. With a rated air leakage the wind enters as pressure
#: (engine.leakage.wind_pressure_pa added to dp_pa), which is the physical
#: form. Kept so older tests and API calls with ach_out= still run.
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
    # Preferred way to set leakage: rated air leakage in cfm/ft2 at 75 Pa
    # (AERC / ASTM E283) plus the operating pressure. When given, ach_out /
    # ach_in are DERIVED from these and the cavity offset (engine.leakage).
    al_out: float | None = None
    al_in: float | None = None
    dp_pa: float = DEFAULT_OPERATING_PA
    # Sealant vapour diffusion, the floor once air leakage is at the test
    # detection limit. Key into engine.leakage.SEALANTS; bead in metres.
    sealant_out: str = DEFAULT_SEALANT
    sealant_in: str = DEFAULT_SEALANT
    bead_width_m: float = DEFAULT_BEAD_WIDTH_M
    bead_depth_m: float = DEFAULT_BEAD_DEPTH_M
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
        if self.dp_pa < 0:
            raise ValueError("dp_pa cannot be negative")
        if self.sealant_out not in SEALANTS or self.sealant_in not in SEALANTS:
            raise ValueError(f"sealant must be one of {sorted(SEALANTS)}")
        if self.bead_width_m < 0 or self.bead_depth_m <= 0:
            raise ValueError("bead width cannot be negative and depth must be positive")
        if self.al_out is not None:
            self.ach_out = ach_from_air_leakage(self.al_out, self.dp_pa, self.geometry.offset_m)
        if self.al_in is not None:
            self.ach_in = ach_from_air_leakage(self.al_in, self.dp_pa, self.geometry.offset_m)
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
    diff_kg_per_m2_h: list[float]


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
    # Net water delivered to the cavity by each source, grams per window.
    # Negative = that path removed water (its air was drier than the cavity).
    net_outdoor_g: float = 0.0
    net_room_g: float = 0.0
    net_diffusion_g: float = 0.0
    # Same, heating season only (October to March). At 0 g the yearly nets
    # nearly cancel (condensate re-evaporates), so the season split is
    # what makes winter drying by cold outdoor air visible.
    heating_outdoor_g: float = 0.0
    heating_room_g: float = 0.0
    heating_diffusion_g: float = 0.0


HEATING_SEASON_HOURS = 2160          # Jan 1 .. Mar 31 = 90 days
HEATING_SEASON_START = 6552          # Oct 1 = day 273 (non-leap TMY)


def in_heating_season(hour_of_year: int) -> bool:
    return hour_of_year < HEATING_SEASON_HOURS or hour_of_year >= HEATING_SEASON_START


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
    # Whole-run net water by source, grams per window (see YearSummary).
    net_outdoor_g: float = 0.0
    net_room_g: float = 0.0
    net_diffusion_g: float = 0.0
    # The same up to the hour the desiccant is full (the desiccant's LIFE),
    # which is the headline question "where did the water in the sieve come
    # from". Equal to the whole-run numbers when it never fills. The run
    # continues past exhaustion to show the aftermath, and with an inactive
    # sieve the aftermath can be thousands of grams passing through, which
    # would otherwise bury the fill.
    life_outdoor_g: float = 0.0
    life_room_g: float = 0.0
    life_diffusion_g: float = 0.0
    # Whole-run daily trace for the long chart: day index, loading, rh_eq,
    # cavity dew point, cold pane min. Length = days run.
    daily_loading: list[float] = field(default_factory=list)
    daily_rh_eq: list[float] = field(default_factory=list)
    daily_cav_dew_c: list[float] = field(default_factory=list)
    daily_pane_min_c: list[float] = field(default_factory=list)
    daily_film_max_kg: list[float] = field(default_factory=list)
    daily_t_out_c: list[float] = field(default_factory=list)
    daily_rh_out: list[float] = field(default_factory=list)
    daily_cond_g: list[float] = field(default_factory=list)
    # First-year hourly trace for the animation.
    year1: dict[str, list[float]] = field(default_factory=dict)
    tables: HourTables | None = field(default=None, repr=False)

    @property
    def exhausted_years(self) -> float | None:
        return None if self.exhausted_hour is None else self.exhausted_hour / 8760.0

    @property
    def first_condensation_days(self) -> float | None:
        return None if self.first_condensation_hour is None else self.first_condensation_hour / 24.0

    def contributions(self) -> dict:
        """Headline split over the desiccant's life (see life_* fields)."""
        return contribution_shares(self.life_outdoor_g, self.life_room_g, self.life_diffusion_g)

    def contributions_run(self) -> dict:
        return contribution_shares(self.net_outdoor_g, self.net_room_g, self.net_diffusion_g)


def contribution_shares(out_g: float, room_g: float, diff_g: float) -> dict:
    """Net contribution of each source as grams and, when every source is a
    source, as a share of the total. Shares are None as soon as any path is
    negative (a remover): "+195 % / -98 %" is not a split anyone can read,
    so the grams carry the story in that case. Also None when the total is
    not positive."""
    total = out_g + room_g + diff_g
    all_sources = out_g >= -1e-9 and room_g >= -1e-9 and diff_g >= -1e-9
    def pct(x):
        return None if (total <= 1e-9 or not all_sources) else 100.0 * x / total
    return {
        "outdoor_g": out_g, "room_g": room_g, "diffusion_g": diff_g, "total_g": total,
        "outdoor_pct": pct(out_g), "room_pct": pct(room_g), "diffusion_pct": pct(diff_g),
    }


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
    a_out_l, a_tot_l, w_sup_l, rise_l, diff_l = [], [], [], [], []
    perim = inp.geometry.perimeter_m
    area = inp.geometry.glazing_area_m2
    pw_room = p_w_from_w(w_room, p_atm)
    j_in = sealant_diffusion_kg_per_h(perim, inp.bead_width_m, inp.bead_depth_m, SEALANTS[inp.sealant_in], pw_room) / area

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

        if inp.wind_scaling and inp.al_out is not None:
            a_out = ach_from_air_leakage(inp.al_out, inp.dp_pa + wind_pressure_pa(wind), gap)
        elif inp.wind_scaling:
            a_out = wind_scaled_ach(inp.ach_out, wind)
        else:
            a_out = inp.ach_out
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
        j_out = sealant_diffusion_kg_per_h(perim, inp.bead_width_m, inp.bead_depth_m, SEALANTS[inp.sealant_out], p_w_from_w(w_out, p_atm)) / area if w_out > 0 else 0.0
        diff_l.append(j_in + j_out)

    return HourTables(
        n=n, t_out_c=list(weather.t_out_c), w_out=w_out_l, t_cold_c=t_cold_l,
        t_air_c=t_air_l, w_sat_cold=w_sat_l, m_cav=m_cav_l, ach_out=a_out_l,
        ach_total=a_tot_l, w_supply=w_sup_l, vent_rise_k=rise_l, w_room=w_room,
        diff_kg_per_m2_h=diff_l,
    )


def coupled_substep(
    w_cav: float, q: float, film: float,
    w_sup: float, w_sat: float, a_tot: float, m_cav: float,
    m_des: float, des: DesiccantType, t_air: float, tau: float, dt: float,
    allow_desorption: bool, p_atm: float, film_cap: float, j_diff: float = 0.0,
) -> tuple[float, float, float, float, float, float]:
    """One substep with air, desiccant and cold pane solved TOGETHER.

    Returns (w_cav, q, film, condensed_kg, uptake_kg, vent_net_kg), all per
    m2 of glass. ``vent_net_kg`` is the NET water the two vent paths
    delivered this substep, a_tot . m_cav . (W_sup - W_op) . dt at the
    operating humidity W_op the step actually ran at; negative means the
    vents carried water OUT. The caller splits it per path (see
    ``split_vent_net``), which is exact because W_sup is a flow-weighted
    mean.

    WHY NOT SPLIT
    -------------
    The cavity air holds ~0.005 g/m2 of water; the desiccant moves ~1 g/m2
    per hour. The air's time constant against the desiccant is seconds, so
    any split scheme with minute or quarter-hour steps either throttles the
    supply (air emptied once per step, uptake capped at one cavity volume
    per step: 5x too slow at 20 ACH) or overshoots on desorption (a step's
    worth of released water dumped into air that cannot hold it, fogging
    the pane spuriously). Treating the air as QUASI-STEADY fixes both.

    THE BALANCE
    -----------
    Rates in kg/m2/h as functions of the cavity humidity W:

        S(W) = a . m_cav . (W_sup - W)             net supply from vents
        D(W) = (m_des / tau) . (q_eq(W) - q)       desiccant uptake (<0 desorbs)

    S falls with W, D rises with W, so S(W) = D(W) has one root W*, found
    by bisection on [min(W_sup, W_eq), max(W_sup, W_eq)] where W_eq is the
    humidity the desiccant is in equilibrium with (D = 0). With no vents
    W* = W_eq exactly.

    THEN THE PANE
    -------------
    If W* >= W_sat(T_cold) the pane is condensing: the air pins at W_sat,
    the desiccant takes D(W_sat).dt and the pane takes the rest of the
    supply. If W* < W_sat and there is a film, the film evaporates to hold
    W_sat until it runs out, feeding desiccant and outflow. Otherwise the
    air sits at W* and the desiccant takes exactly what the vents bring.

    The initial air inventory (W_0 - W_new).m_cav is booked to whichever
    sink takes it so the water balance closes to rounding.
    """
    inv0 = w_cav * m_cav
    q_eq_of = lambda W: des.q_eq(rh_from_t_w(t_air, W, p_atm_pa=p_atm) if W > 0 else 0.0, t_air)
    k_des = m_des / tau

    # Inactive desiccant (cannot take water even from supply-level air and
    # is not allowed to give it back): the air is no longer a fast variable,
    # so use the plain exchange + pane step.
    if not allow_desorption and q_eq_of(max(w_sup, w_cav)) <= q:
        w_cav = w_cav + j_diff * dt / m_cav
        w_new, c, e, film = step_hour(w_cav, w_sup, w_sat, a_tot, m_cav, film, dt)
        film, _d = drain_excess(film, film_cap)
        # Water balance of the closed-form step: vents = inventory change
        # + condensed - evaporated (diffusion already booked to the air).
        vent_net = (w_new - w_cav) * m_cav + c - e
        return w_new, q, film, c, 0.0, vent_net

    def D(W):
        d = k_des * (q_eq_of(W) - q)
        return d if (allow_desorption or d > 0.0) else 0.0

    def S(W):
        return a_tot * m_cav * (w_sup - W) + j_diff       # vents plus sealant diffusion

    # --- quasi-steady humidity W* -------------------------------------
    w_eq = _w_from_rh(des.rh_eq(q, t_air), t_air, p_atm)
    if not allow_desorption and w_eq > w_sup:
        w_eq = w_sup                     # cannot push air above supply without desorbing
    lo, hi = min(w_sup, w_eq), max(w_sup, w_eq)
    if a_tot <= 0.0 and j_diff <= 0.0:
        w_star = w_eq
    elif a_tot <= 0.0:
        w_star = w_eq if j_diff <= 0.0 else _bisect_source(D, j_diff, w_eq, w_sat)
    elif hi - lo < 1e-12:
        w_star = lo
    else:
        for _ in range(48):
            mid = 0.5 * (lo + hi)
            if S(mid) - D(mid) > 0.0:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-9 * max(hi, 1e-6):
                break
        w_star = 0.5 * (lo + hi)

    condensed = 0.0
    uptake = 0.0
    vents = lambda W: a_tot * m_cav * (w_sup - W) * dt      # vent part of S, this substep

    if w_star >= w_sat:
        # pane condensing: air pinned at saturation
        d = D(w_sat) * dt
        supply = S(w_sat) * dt + max(0.0, inv0 - w_sat * m_cav)   # plus the air's own excess
        uptake = d
        condensed = max(0.0, supply - d)
        w_new = w_sat
        film += condensed
        vent_net = vents(w_sat)
    elif film > 0.0 and w_star < w_sat:
        # film present: it feeds the air at saturation until gone
        drain_rate = D(w_sat) - S(w_sat)                     # > 0 here
        headroom = w_sat * m_cav - inv0
        need = drain_rate * dt + headroom
        if need <= film:
            film -= need
            uptake = D(w_sat) * dt
            w_new = w_sat
            vent_net = vents(w_sat)
        else:
            # film runs out part-way through the step: that fraction at
            # saturation, the rest at W*. The last of the film goes to the
            # air (headroom) and is then shared like any other water.
            frac = film / need if need > 0 else 0.0
            uptake = D(w_sat) * dt * frac + D(w_star) * dt * (1.0 - frac)
            film = 0.0
            w_new = w_star
            vent_net = vents(w_sat) * frac + vents(w_star) * (1.0 - frac)
    else:
        # Uptake is rate-based. The air's own inventory change (W_0 -> W*)
        # is ~0.005 g/m2 and belongs to the air, not the desiccant; booking
        # it to the desiccant made loading drift down when supply air got
        # wetter. Water balance closes to that inventory.
        w_new = w_star
        uptake = D(w_star) * dt
        vent_net = vents(w_star)

    if m_des > 0.0:
        q = max(0.0, q + uptake / m_des)
    if film > film_cap:
        film = film_cap
    return w_new, q, film, condensed, uptake, vent_net


def split_vent_net(vent_net: float, a_out: float, w_out: float, a_in: float, w_room: float,
                   m_cav: float, dt: float) -> tuple[float, float]:
    """Split the net vent water of one step into (outdoor, room) parts.

    The step ran at some operating humidity W_op with
        vent_net = a_tot . m . (W_sup - W_op) . dt,   W_sup = (a_out W_out + a_in W_room)/a_tot.
    Recover W_op from vent_net, then each path's own net is
        N_out = a_out . m . (W_out - W_op) . dt,   N_in = a_in . m . (W_room - W_op) . dt,
    and N_out + N_in = vent_net identically. A path is NEGATIVE when its
    air is drier than the cavity: it is carrying water out. That is the
    winter outdoor path (cold air holds little water even at high RH).
    """
    a_tot = a_out + a_in
    if a_tot <= 0.0 or m_cav <= 0.0 or dt <= 0.0:
        return 0.0, 0.0
    w_sup = (a_out * w_out + a_in * w_room) / a_tot
    w_op = w_sup - vent_net / (a_tot * m_cav * dt)
    return a_out * m_cav * (w_out - w_op) * dt, a_in * m_cav * (w_room - w_op) * dt


def _bisect_source(D, j, w_eq, w_sat):
    """No vents, only diffusion: D(W) = j has a root above w_eq (D rises
    with W). Bracket to saturation; if even saturation cannot absorb j the
    pane takes the rest (caller handles W* >= w_sat)."""
    lo, hi = w_eq, max(w_sat, w_eq * 1.01 + 1e-9)
    if D(hi) < j:
        return hi
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        if D(mid) < j:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _w_from_rh(rh: float, t_c: float, p_atm: float) -> float:
    if rh <= 0.0:
        return 0.0
    return w_from_t_rh(t_c, min(rh, 1.0), p_atm_pa=p_atm)


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
    if inp.desiccant_grams < 1e-9:                        # nothing measurable: run without
        m_des = 0.0
    tau = inp.tau
    q_full = inp.full_fraction * des.q_max(25.0)
    p_atm = atmospheric_pressure_pa(weather.elevation_m)
    nsub = max(inp.substeps, int(math.ceil(4.0 / tau)))
    dt = 1.0 / nsub

    # State
    w_cav = tb.w_supply[0]
    film = 0.0
    q = 0.0

    exhausted_hour: int | None = None
    first_cond_hour: int | None = None
    years: list[YearSummary] = []
    total_uptake = 0.0
    run_out = run_in = run_diff = 0.0
    life_out = life_in = life_diff = None

    daily_q, daily_rh, daily_dp, daily_pane, daily_film = [], [], [], [], []
    daily_to, daily_rho, daily_cg = [], [], []
    year1: dict[str, list[float]] = {
        k: [] for k in (
            "t_out_c", "t_cold_c", "t_air_c", "w_cav", "rh_cav", "dew_cav_c",
            "film_kg", "loading", "rh_eq", "uptake_g", "condensed_g", "ach_out",
        )
    }

    hours_run = 0
    for year in range(inp.max_years):
        y_cond = 0.0; y_hc = 0; y_hv = 0; y_up = 0.0; y_dp = 0.0
        y_out = y_in = y_diff = 0.0
        h_out = h_in = h_diff = 0.0
        d_q = d_rh = d_dp = 0.0; d_pane = 1e9; d_film = 0.0; d_n = 0
        d_to = d_rho = d_cg = 0.0

        for i in range(n):
            w_sup = tb.w_supply[i]; w_sat = tb.w_sat_cold[i]
            m_cav = tb.m_cav[i]; a_tot = tb.ach_total[i]; t_air = tb.t_air_c[i]
            hour_cond = 0.0; hour_up = 0.0; hour_vent = 0.0
            a_out = tb.ach_out[i]; a_in = a_tot - a_out; w_out = tb.w_out[i]

            j_diff = tb.diff_kg_per_m2_h[i]
            if m_des > 0.0:
                # Coupled air/desiccant/pane step. Substeps only need to
                # resolve the desiccant's own time constant.
                for _ in range(nsub):
                    w_cav, q, film, c, up, vn = coupled_substep(
                        w_cav, q, film, w_sup, w_sat, a_tot, m_cav, m_des, des, t_air,
                        tau, dt, inp.allow_desorption, p_atm, inp.max_film_kg, j_diff,
                    )
                    hour_cond += c
                    hour_up += up
                    hour_vent += vn
            else:
                w0 = w_cav + j_diff / m_cav                     # diffusion, then exchange
                w_cav, c, e, film = step_hour(w0, w_sup, w_sat, a_tot, m_cav, film, 1.0)
                hour_cond += c
                hour_vent += (w_cav - w0) * m_cav + c - e
                film, _drained = drain_excess(film, inp.max_film_kg)
            n_out, n_in = split_vent_net(hour_vent, a_out, w_out, a_in, tb.w_room, m_cav, 1.0)
            y_out += n_out; y_in += n_in; y_diff += j_diff
            if in_heating_season(i):
                h_out += n_out; h_in += n_in; h_diff += j_diff

            hours_run += 1
            total_uptake += hour_up
            y_cond += hour_cond; y_up += hour_up
            if hour_cond > 0.0:
                y_hc += 1
                if first_cond_hour is None:
                    first_cond_hour = hours_run - 1
            if film > inp.visible_film_kg:
                y_hv += 1
            # A fresh sieve drives W toward zero within hours. Dew point is
            # floored at -40 (same in degC and degF) for the charts; below
            # that the number carries no information.
            dp = max(-40.0, dew_point_from_w(w_cav, p_atm_pa=p_atm)) if w_cav > 1e-6 else -40.0
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
                d_to += tb.t_out_c[i]; d_rho += weather.rh_out[i]; d_cg += hour_cond * 1000.0 * area
                if d_n == 24:
                    daily_q.append(d_q / 24); daily_rh.append(d_rh / 24)
                    daily_dp.append(d_dp / 24); daily_pane.append(d_pane); daily_film.append(d_film)
                    daily_to.append(d_to / 24); daily_rho.append(d_rho / 24); daily_cg.append(d_cg)
                    d_q = d_rh = d_dp = 0.0; d_pane = 1e9; d_film = 0.0; d_n = 0
                    d_to = d_rho = d_cg = 0.0

            if exhausted_hour is None and m_des > 0.0 and q >= q_full:
                exhausted_hour = hours_run
                life_out, life_in, life_diff = run_out + y_out, run_in + y_in, run_diff + y_diff

        years.append(YearSummary(
            year=year + 1, condensed_kg_per_m2=y_cond, hours_condensing=y_hc,
            hours_visible=y_hv, water_into_desiccant_g=y_up * 1000.0 * area,
            loading_end=q, rh_eq_end=des.rh_eq(q, 21.0) if m_des > 0 else 1.0,
            mean_cavity_dew_point_c=y_dp / n,
            net_outdoor_g=y_out * 1000.0 * area, net_room_g=y_in * 1000.0 * area,
            net_diffusion_g=y_diff * 1000.0 * area,
            heating_outdoor_g=h_out * 1000.0 * area, heating_room_g=h_in * 1000.0 * area,
            heating_diffusion_g=h_diff * 1000.0 * area,
        ))
        run_out += y_out; run_in += y_in; run_diff += y_diff
        # Finish the year exhaustion falls in, so first condensation and
        # the animation show the aftermath, then stop.
        if exhausted_hour is not None:
            break

    if life_out is None:
        life_out, life_in, life_diff = run_out, run_in, run_diff

    hpg = None
    if exhausted_hour is not None and m_des > 0.0:
        hpg = exhausted_hour / inp.desiccant_grams

    return LifetimeResult(
        inputs=inp, exhausted_hour=exhausted_hour, first_condensation_hour=first_cond_hour,
        years_run=len(years), hours_run=hours_run, hours_per_gram=hpg,
        final_loading=q, final_rh_eq=des.rh_eq(q, 21.0) if m_des > 0 else 1.0,
        total_water_into_desiccant_g=total_uptake * 1000.0 * area, years=years,
        net_outdoor_g=run_out * 1000.0 * area, net_room_g=run_in * 1000.0 * area,
        net_diffusion_g=run_diff * 1000.0 * area,
        life_outdoor_g=life_out * 1000.0 * area, life_room_g=life_in * 1000.0 * area,
        life_diffusion_g=life_diff * 1000.0 * area,
        daily_loading=daily_q, daily_rh_eq=daily_rh, daily_cav_dew_c=daily_dp,
        daily_pane_min_c=daily_pane, daily_film_max_kg=daily_film,
        daily_t_out_c=daily_to, daily_rh_out=daily_rho, daily_cond_g=daily_cg,
        year1=year1 if keep_year1 else {}, tables=tb,
    )
