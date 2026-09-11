"""
Independent reference model. DO NOT import from engine/.

Purpose: a second, deliberately naive implementation of the same physics,
written from the equations rather than from the engine code, so the two
can be compared. Everything here is explicit Euler on 1-minute steps with
its own psychrometric formulas (Magnus), its own condensation logic and
its own desiccant integration. If the engine's closed-form hour and this
loop agree, the engine's integration is right; where they disagree, the
size of the gap is the integration error.

Method: backward (implicit) Euler on the coupled air/desiccant system with
the step shrunk until a.dt <= 0.05, with the pane applied as a constraint.
The engine instead treats the air as quasi-steady and bisects for the
balance humidity each substep. Different discretisations, same physics.

Scope: air-only pane temperature (f-value), no solar, no sky, no vent
warming, no wind. Those terms are checked separately by hand calcs in
AUDIT.md; this file checks the moisture and desiccant bookkeeping.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Psychrometrics, Magnus form (different from the engine's Hyland-Wexler)
# ---------------------------------------------------------------------------

def p_sat_pa(t_c: float) -> float:
    if t_c >= 0:
        return 610.94 * math.exp(17.625 * t_c / (t_c + 243.04))
    return 611.21 * math.exp(22.587 * t_c / (t_c + 273.86))       # over ice


def w_from_rh(t_c: float, rh: float, p_atm: float = 101325.0) -> float:
    pw = rh * p_sat_pa(t_c)
    return 0.622 * pw / (p_atm - pw)


def rh_from_w(t_c: float, w: float, p_atm: float = 101325.0) -> float:
    pw = w * p_atm / (0.622 + w)
    return min(1.0, max(0.0, pw / p_sat_pa(t_c)))


def w_sat(t_c: float, p_atm: float = 101325.0) -> float:
    return w_from_rh(t_c, 1.0, p_atm)


def rho_dry(t_c: float, p_atm: float = 101325.0) -> float:
    return p_atm / (287.05 * (t_c + 273.15))


# ---------------------------------------------------------------------------
# Desiccant (same isotherm SHAPE, re-typed from the equations)
# ---------------------------------------------------------------------------

@dataclass
class Sieve:
    q_max_25: float = 0.21
    slope: float = 0.005
    k_25: float = 60.0
    k_t: float = 0.03
    tau_h: float = 2.0

    def q_max(self, t):
        return self.q_max_25 * max(0.25, min(1.0, 1.0 - self.slope * (t - 25.0)))

    def q_eq(self, rh, t):
        k = self.k_25 * math.exp(-self.k_t * (t - 25.0))
        rh = min(1.0, max(0.0, rh))
        return self.q_max(t) * k * rh / (1.0 + k * rh)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

@dataclass
class RefResult:
    exhausted_hour: int | None
    first_condensation_hour: int | None
    condensed_kg_per_m2_year1: float
    hours_condensing_year1: int
    loading_by_hour: list[float]
    w_by_hour: list[float]
    total_uptake_kg_per_m2: float


def run_reference(
    t_out_c: list[float], rh_out: list[float],
    f_cold: float, f_warm: float, t_room_c: float, rh_room: float,
    ach_out: float, ach_in: float, gap_m: float,
    grams_per_m2: float, sieve: Sieve = Sieve(), allow_desorption: bool = False,
    full_fraction: float = 0.95, max_years: int = 3, film_cap_kg: float = 0.1,
    h_cold: float = 3.0, h_warm: float = 3.0, cp: float = 1005.0,
    dt_min: float = 1.0, p_atm: float = 101325.0,
) -> RefResult:
    n = len(t_out_c)
    # resolve exchange: keep a.dt <= 0.05 so implicit Euler's own error stays < 3 %
    dt_min = min(dt_min, 3.0 / max(ach_out + ach_in, 1e-9))
    dt = dt_min / 60.0                                  # hours
    steps = min(1200, max(1, int(round(60.0 / dt_min))))
    dt = 1.0 / steps
    m_des = grams_per_m2 / 1000.0
    w_room = w_from_rh(t_room_c, rh_room, p_atm)
    a_tot = ach_out + ach_in
    q_full = full_fraction * sieve.q_max(25.0)

    w = None
    film = 0.0
    q = 0.0
    exhausted = None
    first_cond = None
    cond_y1 = 0.0
    hc_y1 = 0
    loading_by_hour: list[float] = []
    w_by_hour: list[float] = []
    total_uptake = 0.0
    hour_index = 0

    for year in range(max_years):
        for i in range(n):
            t_o = t_out_c[i]
            t_cold = t_o + f_cold * (t_room_c - t_o)
            t_warm = t_o + f_warm * (t_room_c - t_o)
            w_out = w_from_rh(t_o, min(1.0, max(0.0, rh_out[i])), p_atm)
            w_sup = (ach_out * w_out + ach_in * w_room) / a_tot if a_tot > 0 else w_room
            t_stream = (ach_out * t_o + ach_in * t_room_c) / a_tot if a_tot > 0 else t_room_c
            # well-mixed cavity air temperature, re-derived
            rho = rho_dry(0.5 * (t_cold + t_warm), p_atm)
            mdot_cp = a_tot * gap_m * rho / 3600.0 * cp
            t_air = (h_warm * t_warm + h_cold * t_cold + mdot_cp * t_stream) / (h_warm + h_cold + mdot_cp)
            m_cav = gap_m * rho_dry(t_air, p_atm)
            ws = w_sat(t_cold, p_atm)
            if w is None:
                w = w_sup
            hour_cond = 0.0
            for _ in range(steps):
                # Backward Euler on the coupled (W, q) system: find W1 such that
                #   W1 = W0 + dt[ a (Wsup - W1) - (m_des/m_cav) (q1 - q0)/dt ]
                #   q1 = (q0 + (dt/tau) q_eq(W1)) / (1 + dt/tau)
                # by bisection, then apply the pane constraint.
                def q_next(W1):
                    qe = sieve.q_eq(rh_from_w(t_air, W1, p_atm), t_air)
                    q1 = (q + (dt / sieve.tau_h) * qe) / (1.0 + dt / sieve.tau_h)
                    if q1 < q and not allow_desorption:
                        q1 = q
                    return q1
                def resid(W1):
                    return W1 - (w + dt * a_tot * (w_sup - W1) - (m_des / m_cav) * (q_next(W1) - q))
                lo, hi = 0.0, max(w, w_sup, ws) * 1.5 + 1e-6
                for _k in range(60):
                    mid = 0.5 * (lo + hi)
                    if resid(mid) < 0.0:
                        lo = mid
                    else:
                        hi = mid
                    if hi - lo < 1e-13:
                        break
                W1 = 0.5 * (lo + hi)
                if W1 > ws:
                    # pane condensing: pin at ws, desiccant follows ws, pane takes the rest
                    W1 = ws
                    q1 = q_next(ws)
                    inflow = dt * a_tot * (w_sup - ws) * m_cav
                    c = w * m_cav + inflow - (q1 - q) * m_des - ws * m_cav
                    c = max(0.0, c)
                    hour_cond += c
                    film += c
                elif film > 0.0 and W1 < ws:
                    # film feeds the air at saturation while it lasts
                    q1 = q_next(ws)
                    inflow = dt * a_tot * (w_sup - ws) * m_cav
                    need = ws * m_cav - w * m_cav - inflow + (q1 - q) * m_des
                    if need <= film:
                        film -= need
                        W1 = ws
                    else:
                        q1 = q_next(W1)
                        film = 0.0
                else:
                    q1 = q_next(W1)
                total_uptake += (q1 - q) * m_des
                q = q1
                w = W1
                if film > film_cap_kg:
                    film = film_cap_kg
            if hour_cond > 0.0:
                if first_cond is None:
                    first_cond = hour_index
                if year == 0:
                    hc_y1 += 1
            if year == 0:
                cond_y1 += hour_cond
            loading_by_hour.append(q)
            w_by_hour.append(w)
            if exhausted is None and m_des > 0.0 and q >= q_full:
                exhausted = hour_index + 1
            hour_index += 1
        if exhausted is not None:
            break

    return RefResult(exhausted, first_cond, cond_y1, hc_y1, loading_by_hour, w_by_hour, total_uptake)
