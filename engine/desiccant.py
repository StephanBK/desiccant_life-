"""
Desiccant physics for the vented SWR cavity.

WHAT THIS MODULE ANSWERS
------------------------
How much water a given mass of desiccant can hold under the humidity and
temperature it actually sees in the cavity, and how fast it takes that
water out of the cavity air. The lifetime solver (engine/lifetime.py) calls
this every hour.

THE THREE IDEAS
---------------
1. ISOTHERM. A desiccant does not have one capacity. Its equilibrium loading
   q_eq (kg water per kg desiccant) depends on the relative humidity of the
   air around it and on temperature. Molecular sieve is a Type I (Langmuir)
   adsorbent: it fills steeply at very low RH and then flattens, which is
   exactly why it is the IGU spacer standard - it keeps pulling water out of
   air that is already dry.

       q_eq(RH, T) = q_max(T) . K(T).RH / (1 + K(T).RH)

2. TEMPERATURE. Adsorption is exothermic, so hot desiccant holds less.
   q_max falls with temperature and so does the affinity K. In summer the
   cavity can run 50-70 degC in sun, which is where a desiccant gives
   water back if it is allowed to (see ``allow_desorption``).

3. RATE. Beads take minutes at the surface and hours in the core, and in a
   cartridge or spacer the air contact is limited. First-order approach to
   equilibrium with a time constant tau:

       dq/dt = (q_eq - q) / tau        =>   q(t+dt) = q_eq + (q - q_eq).exp(-dt/tau)

   tau is a USER INPUT with a default. It is the least certain number in the
   module and the one a vendor can measure.

ESTIMATES, NOT MEASUREMENTS
---------------------------
The 3A curve below is fitted to published vendor isotherms (Grace SYLOBEAD,
UOP MOLSIV, generic 3A data): about 0.21 kg/kg at 25 degC above 30 % RH,
0.18 at 10 % RH, 0.08 at 1 % RH, falling to roughly 0.15 kg/kg at 60 degC.
Replace with a specific vendor sheet when INOVUES picks a supplier. Every
number is labelled ESTIMATE in the UI until then.

SI throughout. kg, K, fractions. See engine/psychro.py.

Doc ID: ANLY-003 (desiccant lifetime), Chunk 1
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DesiccantType:
    """One desiccant and the numbers that describe it.

    q_max_25
        Saturation loading at 25 degC, kg water / kg dry desiccant.
    q_max_slope_per_k
        Fractional loss of q_max per kelvin above 25 degC. 0.005 means 0.5 %
        per K, i.e. 17.5 % less capacity at 60 degC. Linear over the cavity
        range; clamped to [0.25, 1.0] x q_max_25 (no bonus below 25 degC).
    k_25
        Langmuir affinity at 25 degC, per unit RH (RH as a fraction).
        Higher means the curve rises faster at low RH.
    k_temp_coeff
        K(T) = k_25 . exp(-k_temp_coeff . (T - 25)). Affinity weakens with
        heat; 0.03 halves K every 23 K.
    tau_hours
        Default first-order time constant, hours.
    bulk_density_kg_m3
        For converting grams to the volume the cartridge needs.
    """

    key: str
    name: str
    q_max_25: float
    q_max_slope_per_k: float
    k_25: float
    k_temp_coeff: float
    tau_hours: float
    bulk_density_kg_m3: float
    source: str

    def q_max(self, t_c: float) -> float:
        """Saturation loading at temperature, kg/kg."""
        factor = 1.0 - self.q_max_slope_per_k * (t_c - 25.0)
        # No credit for cold: real 3A gains only a few percent below 25 degC
        # and leaving it out keeps every lifetime number conservative.
        return self.q_max_25 * max(0.25, min(1.0, factor))

    def affinity(self, t_c: float) -> float:
        return self.k_25 * math.exp(-self.k_temp_coeff * (t_c - 25.0))

    def q_eq(self, rh: float, t_c: float) -> float:
        """Equilibrium loading at (RH, T), kg water per kg desiccant.

        Langmuir. RH clamped to [0, 1]; above saturation the desiccant sees
        liquid water and the isotherm is meaningless, so it is pinned at 1.
        """
        rh = min(max(rh, 0.0), 1.0)
        k = self.affinity(t_c)
        return self.q_max(t_c) * k * rh / (1.0 + k * rh)

    def rh_eq(self, q: float, t_c: float) -> float:
        """Inverse isotherm: the RH the desiccant holds the air at when its
        loading is q. This is the number that explains why a nearly full
        sieve stops protecting the pane long before it is 'full'.

            RH = q / (K . (q_max - q))
        """
        q_max = self.q_max(t_c)
        if q <= 0.0:
            return 0.0
        if q >= q_max:
            return 1.0
        return min(1.0, q / (self.affinity(t_c) * (q_max - q)))


#: The library. Only 3A for now, by decision (Sep 10 2026). The dataclass is
#: general so 4A, silica gel and CaCl2 can be added as rows without code.
DESICCANTS: dict[str, DesiccantType] = {
    "ms3a": DesiccantType(
        key="ms3a",
        name="Molecular sieve 3A",
        q_max_25=0.21,
        q_max_slope_per_k=0.005,
        k_25=60.0,
        k_temp_coeff=0.03,
        tau_hours=2.0,
        bulk_density_kg_m3=700.0,
        source=(
            "ESTIMATE fitted to published 3A vendor isotherms. Replace with "
            "supplier data sheet."
        ),
    ),
}

DEFAULT_DESICCANT = "ms3a"


# ---------------------------------------------------------------------------
# The uptake step
# ---------------------------------------------------------------------------

def uptake_step(
    q: float,
    q_eq: float,
    tau_hours: float,
    dt_hours: float,
    allow_desorption: bool = False,
) -> float:
    """Advance loading by ``dt_hours``. Returns the new q.

    Exact solution of dq/dt = (q_eq - q)/tau, so it cannot overshoot at any
    step size (same reasoning as engine.moisture.exchange_analytic).

    With ``allow_desorption=False`` the loading can only rise: if the air is
    drier than the desiccant's equilibrium, nothing happens. That is the
    conservative case (no summer regeneration credit). With True the
    desiccant follows the isotherm both ways.
    """
    if tau_hours <= 0:
        raise ValueError(f"tau_hours must be positive, got {tau_hours}")
    if dt_hours <= 0:
        raise ValueError(f"dt_hours must be positive, got {dt_hours}")
    if q < 0:
        raise ValueError(f"q cannot be negative, got {q}")
    if q_eq < q and not allow_desorption:
        return q
    return q_eq + (q - q_eq) * math.exp(-dt_hours / tau_hours)


def water_removed_kg(
    q_before: float, q_after: float, mass_desiccant_kg: float
) -> float:
    """Water moved from cavity air INTO the desiccant, kg. Negative when the
    desiccant gives water back."""
    if mass_desiccant_kg < 0:
        raise ValueError(f"mass_desiccant_kg cannot be negative, got {mass_desiccant_kg}")
    return (q_after - q_before) * mass_desiccant_kg


def cartridge_volume_ml(grams: float, desiccant: DesiccantType) -> float:
    """Bulk volume the beads occupy, millilitres, for the geometry check."""
    if grams < 0:
        raise ValueError(f"grams cannot be negative, got {grams}")
    return grams / desiccant.bulk_density_kg_m3 * 1e6 / 1000.0
