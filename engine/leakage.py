"""
Air leakage (the number on a certificate) to cavity air changes per hour.

WHY THIS MODULE
---------------
Window and attachment products are rated for air leakage by test, in
cfm/ft2 at a 75 Pa pressure difference (ASTM E283 / NFRC 400, the basis of
the AERC certified-product database). A cavity between an existing window
and a retrofit never sees 75 Pa; it sees the few pascals of stack effect
and wind. This module bridges the two so that the leakage inputs to the
model are numbers a user can read off an AERC certificate or a test report.

THE CONVERSION
--------------
    q75  = AL x 18.29                         m3/h per m2 of window at 75 Pa
    q    = q75 x (dP / 75)^n                  crack flow power law, n = 0.65
    ACH  = q / offset                         cavity volume per m2 = offset

18.29 converts cfm/ft2 to m3/h/m2 (1 cfm = 1.699 m3/h; 1 ft2 = 0.0929 m2).
n = 0.65 is the standard crack-flow exponent (ASHRAE Fundamentals, ch. 16;
laminar would be 1.0, orifice 0.5).

OPERATING PRESSURE
------------------
    stack:  dP = rho g H dT / T   ~ 1.2 x 9.81 x 2.44 x 25 / 283 = 2.5 Pa
            for an 8 ft window and a 25 K indoor-outdoor difference
    wind:   dP = 0.5 rho v^2 Cp   ~ 0.5 x 1.2 x 16 x 0.6 = 5.8 Pa at 4 m/s
Default operating pressure 3 Pa; the outdoor path adds the wind term hour
by hour when wind scaling is on. Both are ESTIMATES of the split of the
room-to-outdoor pressure difference across the two layers; in series the
tighter layer takes most of it, which is why the same dP is applied to
each path rather than half.

WHAT IT ASSUMES
---------------
All air that passes the layer passes through the cavity (true for a
two-layer assembly whenever there is any room-to-outdoor pressure
difference). Diffusion through gaskets at zero pressure is ignored; it is
small next to a few pascals of crack flow. Uncertainty on the derived ACH
is roughly a factor of 3, dominated by the operating pressure.

REFERENCES
----------
[AERC]  Attachments Energy Rating Council, Certified Product Search
        (Commercial). https://aercenergyrating.org/product-search/commercial-product-search/
        Rates U-factor, SHGC, VT and Air Leakage of secondary windows over a
        single-pane aluminium baseline. Baseline single-pane air leakage
        2.0 cfm/ft2; best-in-class certified insert assembly 0.06 cfm/ft2
        (Alpen WinSert, certified Dec 2021).
[E283]  ASTM E283, air leakage through windows at 75 Pa (1.57 psf).
[AAMA]  AAMA/WDMA/CSA 101: 0.3 cfm/ft2 allowable for operable windows;
        fixed windows commonly specified at 0.06 cfm/ft2.
[ASHRAE] Fundamentals ch. 16, crack flow exponent 0.65.
"""

from __future__ import annotations

from dataclasses import dataclass

CFM_FT2_TO_M3H_M2 = 1.699 / 0.09290     # 18.29
TEST_PRESSURE_PA = 75.0
FLOW_EXPONENT = 0.65
DEFAULT_OPERATING_PA = 3.0
WIND_CP = 0.6
RHO_AIR = 1.2


def ach_from_air_leakage(al_cfm_ft2: float, dp_pa: float, offset_m: float,
                         exponent: float = FLOW_EXPONENT) -> float:
    """Cavity air changes per hour from a rated air leakage."""
    if al_cfm_ft2 < 0:
        raise ValueError(f"air leakage cannot be negative, got {al_cfm_ft2}")
    if dp_pa < 0:
        raise ValueError(f"operating pressure cannot be negative, got {dp_pa}")
    if offset_m <= 0:
        raise ValueError(f"offset must be positive, got {offset_m}")
    if not 0.5 <= exponent <= 1.0:
        raise ValueError(f"flow exponent must be in [0.5, 1.0], got {exponent}")
    q75 = al_cfm_ft2 * CFM_FT2_TO_M3H_M2
    q = q75 * (dp_pa / TEST_PRESSURE_PA) ** exponent
    return q / offset_m


def air_leakage_from_ach(ach: float, dp_pa: float, offset_m: float,
                         exponent: float = FLOW_EXPONENT) -> float:
    """Inverse: what rated leakage would give this ACH."""
    if ach < 0:
        raise ValueError("ach cannot be negative")
    if dp_pa <= 0 or offset_m <= 0:
        raise ValueError("dp_pa and offset_m must be positive")
    q = ach * offset_m
    return q / (dp_pa / TEST_PRESSURE_PA) ** exponent / CFM_FT2_TO_M3H_M2


def wind_pressure_pa(wind_m_s: float, cp: float = WIND_CP) -> float:
    """Stagnation pressure on the facade, 0.5 rho v^2 Cp."""
    if wind_m_s < 0:
        wind_m_s = 0.0
    return 0.5 * RHO_AIR * wind_m_s ** 2 * cp


def stack_pressure_pa(height_m: float, dt_k: float, t_mean_k: float = 283.0) -> float:
    """Buoyancy pressure across a window of height H with an indoor-outdoor
    difference dT. Used only in documentation and tests; the model takes the
    operating pressure as an input because the split between layers is not
    known."""
    return RHO_AIR * 9.81 * height_m * abs(dt_k) / t_mean_k


@dataclass(frozen=True)
class LeakagePreset:
    key: str
    label: str
    al_cfm_ft2: float
    source: str
    estimate: bool


#: Existing window: leakage from OUTDOORS into the cavity. Tightest first.
EXISTING_PRESETS: list[LeakagePreset] = [
    LeakagePreset("hermetic", "Hermetic, IGU-grade (diffusion only)", 0.0, "Estimate: no crack flow at all; see the retrofit preset of the same name", True),
    LeakagePreset("wet_sealed", "Wet-sealed, continuous bead", 0.005, "Estimate: continuous silicone bead over all joints, at the ASTM E283 detection floor; verify by cavity pressurisation test", True),
    LeakagePreset("new_fixed", "New fixed window", 0.06, "AAMA/ASTM E283 fixed-window specification", False),
    LeakagePreset("resealed", "Freshly resealed", 0.10, "Estimate: wet-sealed perimeter, serviceable gaskets", True),
    LeakagePreset("operable", "Operable, in spec", 0.30, "AAMA/WDMA/CSA 101 allowable for operable windows", False),
    LeakagePreset("aged", "Aged, worn gaskets", 1.00, "Estimate: between spec and AERC baseline", True),
    LeakagePreset("baseline", "AERC baseline single-pane", 2.00, "AERC commercial rating baseline window", False),
]

#: Retrofit: leakage from the ROOM into the cavity. Tightest first.
RETROFIT_PRESETS: list[LeakagePreset] = [
    LeakagePreset("hermetic", "Hermetic, IGU-grade (diffusion only)", 0.0, "Estimate: no crack flow at all, as an insulating-glass edge seal; sealant vapour diffusion and thermal breathing remain. UNVERIFIED for a field-applied wet seal; the E283 floor below is the other end of the same unknown", True),
    LeakagePreset("wet_sealed", "Wet-sealed, continuous bead", 0.005, "Estimate: INOVUES practice, continuous silicone bead on a fixed frame, at the ASTM E283 detection floor; verify by cavity pressurisation test", True),
    LeakagePreset("gasketed", "Well-gasketed fixed insert", 0.01, "Estimate: compression gasket on all four sides", True),
    LeakagePreset("certified_best", "Best certified insert", 0.06, "AERC best-in-class (Alpen WinSert, Dec 2021)", False),
    LeakagePreset("certified_typical", "Typical certified insert", 0.30, "Estimate at the AAMA operable allowable", True),
    LeakagePreset("vented", "Deliberate vent slots", 2.00, "Estimate: Eurac CFD open configuration is of this order", True),
]

EXISTING_BY_KEY = {p.key: p for p in EXISTING_PRESETS}
RETROFIT_BY_KEY = {p.key: p for p in RETROFIT_PRESETS}


# ---------------------------------------------------------------------------
# Vapour diffusion through the sealant bead
# ---------------------------------------------------------------------------
# A continuous silicone bead stops air but passes water vapour; this is
# why insulating glass units use polyisobutylene as the primary seal.
# Once air leakage is at the detection floor, diffusion is the floor.
#
#     J = P_perm . A . dp_v / L        kg/h of water into the cavity
#
# with P_perm the sealant's water-vapour permeability, A the bead's
# exposed area (perimeter x joint width), L the diffusion path (bead
# depth) and dp_v the vapour-pressure difference across it. The cavity
# side is taken as dry (desiccant present), which is the upper bound.
#
# Permeabilities, ASTM E96 wet cup at 38 degC / 90 % RH (dp_v ~ 5,960 Pa),
# expressed per pascal. ESTIMATES from published ranges: silicone sealants
# 20-40 g.mm/m2/day, PIB 0.2-0.5.

@dataclass(frozen=True)
class Sealant:
    key: str
    name: str
    perm_g_mm_per_m2_day_pa: float
    source: str


SEALANTS: dict[str, Sealant] = {
    "silicone": Sealant("silicone", "Silicone (DOWSIL 795 class)", 30.0 / 5960.0,
                        "ESTIMATE: ASTM E96 range for silicone building sealants, 20-40 g.mm/m2/day at 38 degC/90 % RH"),
    "pib": Sealant("pib", "Polyisobutylene (IGU primary seal)", 0.3 / 5960.0,
                   "ESTIMATE: ASTM E96 range for PIB, 0.2-0.5 g.mm/m2/day"),
    "none": Sealant("none", "No diffusion term", 0.0, "Diffusion ignored"),
}
DEFAULT_SEALANT = "silicone"
DEFAULT_BEAD_WIDTH_M = 0.25 * 0.0254     # ASTM C1193 minimum joint, 1/4 in
DEFAULT_BEAD_DEPTH_M = 0.25 * 0.0254


def sealant_diffusion_kg_per_h(perimeter_m: float, bead_width_m: float, bead_depth_m: float,
                               sealant: Sealant, dp_vapor_pa: float) -> float:
    """Water diffusing through the bead, kg/h, for a dry cavity."""
    if perimeter_m < 0 or bead_width_m < 0:
        raise ValueError("perimeter and bead width cannot be negative")
    if bead_depth_m <= 0:
        raise ValueError("bead depth must be positive")
    if sealant.perm_g_mm_per_m2_day_pa <= 0.0 or dp_vapor_pa <= 0.0:
        return 0.0
    area = perimeter_m * bead_width_m
    g_per_day = sealant.perm_g_mm_per_m2_day_pa * area * dp_vapor_pa / (bead_depth_m * 1000.0)
    return g_per_day / 1000.0 / 24.0
