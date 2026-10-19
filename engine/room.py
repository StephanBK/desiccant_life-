"""
Room air humidity: a fixed RH, or an unhumidified building.

WHY (Oct 19 2026)
-----------------
The fixed room RH (one number for every hour of the year) decided the
2000 Colorado Avenue result (CU Boulder, Gamow Tower, floor 10 offices):
the report assumed 20 % and predicted fog, the building showed none. An
unhumidified building has no fixed RH. Heating adds no water, so the room
air carries the outdoor air's moisture plus what the occupants add:

    W_room(h) = W_out(h) + dW_people(h)          kg water / kg dry air

In a cold, dry climate that is far drier than a fixed 20 to 35 % (Boulder in
the hours below 25 F: median 8 % RH at 68 F before people). In a humid
winter climate it can be WETTER than the fixed value (Seattle: about 44 % at
70 F with office occupants). So this mode is not "less fog everywhere"; it is
the physically right room air for a building without humidification.
"fixed" stays the default; nothing changes unless a caller asks for this.

PEOPLE (occupied hours)
-----------------------
    one seated person, computer or office work, room at 20 C:
        36 to 44 W latent   (occupant heat-gain table as reproduced by
                             Engineering ToolBox from the ASHRAE / ISO tables)
        water = latent / h_fg = 36 x 3600 / 2450 = 53 g/h  to  65 g/h
    office outdoor air, ASHRAE 62.1 default occupancy 5 per 1000 ft2:
        17 cfm per person = 28.9 m3/h x 1.20 kg/m3 = 34.7 kg/h at sea level
    dW = water / air:
        1.5 to 1.9 g/kg at full design occupancy
        1.1 to 1.3 g/kg at 70 % of design occupancy (air stays at design)
        0.8 to 0.9 g/kg at 50 %
    DEFAULT 1.2 g/kg (about 70 % occupancy). ESTIMATE; a parameter.

Real offices often get more air than the 62.1 minimum (economiser hours,
infiltration), which lowers dW; the occupied window here (the HVAC schedule,
weekdays 07 to 19) is longer than people actually sit there. Both make 1.2 a
middle value, not a floor.

ALTITUDE
--------
The same people in the same volume of outdoor air add more water per kg of
air where the air is thinner: dW scales with P_sea / P_site (x1.22 in
Boulder, 83.2 kPa).

AFTER HOURS
-----------
When the occupants leave, their moisture is diluted away by outdoor air:

    dW(h) = dW(h-1) . exp(-ACH_fade . 1 h)       ACH_fade default 0.5 / h

0.5 per hour is an ESTIMATE (infiltration with the outdoor-air damper at
night setback); a building that ventilates all night fades faster.
ACH_fade = 0 keeps the occupants' moisture in the room around the clock
(an upper bound).

COOLING AND CEILING
-------------------
Above 60 F outdoors the room is capped at 60 % RH (air conditioning dries
the room). Fog on the cavity side needs a cold pane, so this only removes
warm-weather artefacts. The room never exceeds 99 % RH at room temperature.

PERIODIC
--------
The weather year repeats, so the series is computed over two passes of the
year and the second pass kept: January 1 continues from December 31.
"""

from __future__ import annotations

import math
from typing import Callable, Sequence

from engine.psychro import rh_from_t_w, w_from_t_rh

ROOM_HUMIDITY_MODES: tuple[str, ...] = ("fixed", "unhumidified")
DEFAULT_ROOM_HUMIDITY = "fixed"
DEFAULT_PEOPLE_GKG = 1.2
DEFAULT_PEOPLE_FADE_ACH = 0.5
MAX_PEOPLE_GKG = 10.0
MAX_PEOPLE_FADE_ACH = 50.0

P_SEA_PA = 101325.0
COOLING_ABOVE_C = (60.0 - 32.0) / 1.8          # 60 F
COOLING_CAP_RH = 0.60
ROOM_RH_CEILING = 0.99


def people_dw(people_gkg: float, p_atm_pa: float) -> float:
    """Occupant moisture in kg/kg at the site pressure (input is g/kg at sea level)."""
    if people_gkg < 0:
        raise ValueError("people moisture cannot be negative")
    if p_atm_pa <= 0:
        raise ValueError("pressure must be positive")
    return people_gkg / 1000.0 * P_SEA_PA / p_atm_pa


def outdoor_w(t_out_c: float, rh_out: float, p_atm_pa: float) -> float:
    """Outdoor humidity ratio, clamped exactly as the hour tables clamp it."""
    rh = min(max(rh_out, 0.0), 1.0)
    return w_from_t_rh(t_out_c, rh, p_atm_pa=p_atm_pa) if rh > 0 else 0.0


def unhumidified_room_w(
    t_out_c: Sequence[float],
    rh_out: Sequence[float],
    t_room_c: float,
    p_atm_pa: float,
    is_occupied: Callable[[int], bool],
    people_gkg: float = DEFAULT_PEOPLE_GKG,
    fade_ach: float = DEFAULT_PEOPLE_FADE_ACH,
) -> list[float]:
    """Hourly room humidity ratio (kg/kg) of a building without humidification."""
    n = len(t_out_c)
    if n == 0 or len(rh_out) != n:
        raise ValueError("t_out_c and rh_out must be the same non-zero length")
    if not 0.0 <= fade_ach <= MAX_PEOPLE_FADE_ACH:
        raise ValueError(f"fade_ach must be within 0..{MAX_PEOPLE_FADE_ACH}")
    g = people_dw(people_gkg, p_atm_pa)
    keep = math.exp(-fade_ach)
    w_cool = w_from_t_rh(t_room_c, COOLING_CAP_RH, p_atm_pa=p_atm_pa)
    w_ceiling = w_from_t_rh(t_room_c, ROOM_RH_CEILING, p_atm_pa=p_atm_pa)
    out = [0.0] * n
    dw = 0.0
    for k in range(2 * n):
        i = k % n
        dw = g if is_occupied(i) else dw * keep
        if k < n:
            continue
        w = outdoor_w(t_out_c[i], rh_out[i], p_atm_pa) + dw
        if t_out_c[i] > COOLING_ABOVE_C:
            w = min(w, w_cool)
        out[i] = min(w, w_ceiling)
    return out


def room_rh_summary(w_room_h: Sequence[float] | None, w_room_fixed: float, t_room_c: float,
                    p_atm_pa: float, hours: Callable[[int], bool], n: int = 8760) -> dict:
    """Room RH (%) at room temperature over the selected hours: median, 10th
    and 90th percentile. A fixed room gives the same number three times."""
    if w_room_h is None:
        rh = 100.0 * rh_from_t_w(t_room_c, w_room_fixed, p_atm_pa=p_atm_pa)
        return {"median_pct": round(rh, 1), "p10_pct": round(rh, 1), "p90_pct": round(rh, 1)}
    vals = sorted(100.0 * rh_from_t_w(t_room_c, w_room_h[i], p_atm_pa=p_atm_pa)
                  for i in range(min(n, len(w_room_h))) if hours(i))
    if not vals:
        return {"median_pct": None, "p10_pct": None, "p90_pct": None}
    pick = lambda q: vals[min(len(vals) - 1, int(q * (len(vals) - 1) + 0.5))]
    return {"median_pct": round(pick(0.5), 1), "p10_pct": round(pick(0.1), 1), "p90_pct": round(pick(0.9), 1)}
