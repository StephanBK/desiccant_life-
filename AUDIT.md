# AUDIT — Desiccant Lifetime Simulator (ANLY-003)

Date: 2026-09-11. Auditor: Claude, at Stephan Ketterer's request. Scope: every
equation and simplification in `engine/`, with an estimate of the size and
sign of the error it introduces. Sign convention: **+** means the
simplification makes desiccant life look LONGER than reality (optimistic),
**−** shorter (conservative), **±** either way.

Sensitivities below were measured on 277 Park, 60 × 96 × 0.6 in cavity,
500 g 3A, existing window 0.10 cfm/ft², three retrofit leakages (0.06,
0.01, 0.0002 cfm/ft²). Fill times 14 / 19 / 21 h. "Fill" = hours to 95 %
of 25 °C capacity.

## 1. Ranking, largest first

| # | Item | Effect on fill time | Sign | Status |
|---|------|--------------------|------|--------|
| 1 | Operating pressure across each layer (default 3 Pa) | ±25 % for 1.5 ↔ 6 Pa; factor ~3 over the plausible range | ± | input; estimate |
| 2 | Leakage mechanism: independent paths vs series through-flow vs single-sided stack loop | factor 2 to 3 | + (model likely over-supplies) | see §3.1 |
| 3 | Existing-window leakage value | 0.06 → 2.0 cfm/ft² halves-to-quarters fill time | ± | input; two published anchors |
| 4 | Wind as added pressure on the outdoor path | −20 to −50 % vs no wind | − when on | toggle, default on |
| 5 | Desiccant time constant τ (default 2 h) | +80 to +107 % at 8 h; −14 % at 0.5 h | ± | input; unmeasured |
| 6 | Isotherm affinity K at low RH (×0.5 → +21 to +95 %) | large at hermetic leakage where cavity RH is low | ± | fitted; vendor sheet needed |
| 7 | Isotherm temperature dependence (off → +7 to +43 %) | grows as cavity runs hot | ± | fitted |
| 8 | "Full" threshold 0.95 (0.90 → −11 to −14 %; 0.99 never reached at 35 % RH) | definitional | n/a | input; documented |
| 9 | Constant room RH (25 ↔ 50 % → ±5 to 14 % fill; first fog 28 ↔ 284 h) | small on fill, large on fog | ± | input; seasonal RH not modelled |
| 10 | q_max ±10 % | ±5 to 10 %, linear | ± | vendor sheet |
| 11 | Psychrometric formulation (Hyland-Wexler vs Magnus) | 0.2 % in W; up to 10 % on condensation mass in marginal hours | ± | fine |
| 12 | Substeps 4 vs 24 | 0 % | none | fine |
| 13 | Sun, sky, orientation, pane coupling, offset | 0 % on fill; sky decides first fog (5,830 vs 264 h) | see §3.6 | fine for fill |
| 14 | Desorption toggle | 0 % on fill at these leakages; −16 % condensation | + if on | fine |
| 15 | TMY repeated, no year-to-year variation | unquantified; fill times are days so the year matters less than the month | ± | note |

Bottom line: at any leakage a certified attachment reaches (≥ 0.06 cfm/ft²
on either side), fill time is set by supply = crack flow × humidity, and the
uncertainty is the leakage-to-ACH conversion (items 1 to 4), a factor of
about 3. Everything else is second order until both sides are IGU-tight,
where the isotherm's low-RH shape (6, 7) and τ (5) take over.

## 2. Cross-check against an independent model

`tests/reference_model.py`: backward-Euler on the coupled air/desiccant
system with steps shrunk until ACH·dt ≤ 0.1, Magnus psychrometrics, no
engine imports. The engine uses a quasi-steady coupled step
(`engine.lifetime.coupled_substep`). Thirteen scenarios, fill hour:

| scenario | engine | reference | diff |
|---|---|---|---|
| 50 g, 1 / 0.5 ACH | 27 | 27 | 0 % |
| 50 g, 14.75 / 8.85 (AERC default) | 7 | 7 | 0 % |
| 500 g, 14.75 / 8.85 | 17 | 17 | 0 % |
| 500 g, 230 / 8.85 (AERC baseline window) | 7 | 7 | 0 % |
| 50 g, 0.02 / 0.1 | 245 | 239 | +2.5 % |
| 50 g, 0.002 / 0.005 | 4,052 | 4,033 | +0.5 % |
| 50 g, 0.002 / 0.005, desorption | 4,052 | 4,058 | −0.1 % |
| 200 g, 0.5 / 0.5, desorption | 145 | 144 | +0.7 % |
| 2,000 g, 1 / 0.5, τ 12 h | 985 | 977 | +0.8 % |
| 2,000 g, 1 / 0.5, τ 0.25 h | 978 | 968 | +1.0 % |

Condensation (no desiccant): constant-condition test reproduces the
analytic rate a·m_cav·(W_sup − W_sat) within 4 % in both models. On TMY
weather the sealed case differs by 10 % because the supply-to-saturation
margin is 5 % and the two psychrometric formulations differ by 0.2 %;
marginal hours flip.

Bugs found and fixed by this cross-check (commit "Coupled air/desiccant/pane
substep"):

1. Operator splitting throttled desiccant uptake to one cavity volume of
   air per substep. 500 g at 24 ACH read 98 h; true value 17 h (hand
   calculation: 24 ACH × 18 g air × 3.3 g/kg × 3.7 m² = 5.3 g/h into
   100 g). Sign of the old error: **+ 5×**.
2. Stiffness: the air holds ~0.005 g/m² against a desiccant moving
   ~0.7 g/m²/h (air time constant seconds). Quarter-hour desorption steps
   overshot, pushed air above pane saturation, produced spurious spring
   fog and inflated desorption benefits (+50 % life). All artefact.
3. Booking the air inventory change to the desiccant made loading drift
   downward with desorption off.

## 3. Equation-by-equation

### 3.1 Leakage → cavity ACH (`engine/leakage.py`)

    ACH = AL × 18.29 × (ΔP / 75)^0.65 / offset

- AL is measured at 75 Pa (ASTM E283). The 0.65 exponent is the textbook
  crack-flow value; 0.5 (orifice) to 0.7 (long cracks) is the real range.
  Effect ±15 % at 3 Pa.
- ΔP: the model applies the same operating pressure to each layer. In a
  two-layer assembly with an overall room-to-outdoor pressure the flow is
  a series through-flow limited by the tighter layer; without an overall
  pressure the exchange is a single-sided stack loop through each layer's
  own top and bottom cracks. Estimate of the loop flow for an 8 ft window,
  20 K, AL 0.10: effective leakage area 7.6e-5 m²/m², stack pressure at
  each opening ~1 Pa, Q ≈ 0.6 × (A/2) × √(2·1/1.2) = 0.106 m³/h/m² →
  6.9 ACH in a 0.6 in cavity, against 14.8 ACH from the 3 Pa through-flow
  form. The model is therefore likely **optimistic on supply by ~2×** for a
  tight-one-side assembly, i.e. **conservative on life**. Sign −. Kept as
  is; stated in the UI.
- Wind: 0.5ρv²·Cp with Cp = 0.6 is the windward-face value; leeward is
  −0.3 (suction, same magnitude of exchange). Applied only to the outdoor
  path. −20 to −50 % on fill.
- Offset: cancels. Crack flow per m² of window is independent of cavity
  depth; the water delivered per hour is the same. Earlier text claiming
  deeper cavities help was wrong and is corrected.
- Diffusion through gaskets at zero pressure is ignored (MVTR); it is what
  limits an IGU, and it is why the IGU-grade preset is labelled
  hypothetical: at 0.0002 cfm/ft² the model still applies crack-flow
  scaling, which is not the physics of a sealed edge.

### 3.2 Cavity air inventory and supply (`engine/moisture.py`, `engine/lifetime.py`)

    dW/dt = ACH_out (W_out − W) + ACH_in (W_room − W)

- Perfect mixing assumed. Real cavities stratify; the desiccant cartridge
  sits at the bottom and sees whatever air reaches it. Effect on fill
  time: none as long as the sieve is supply-limited (it eats everything
  that arrives); could lengthen life if part of the supply bypasses the
  cartridge and exits. Sign +, unquantified, likely < 20 %.
- Room RH constant. Real offices run 20 to 30 % in winter and 50 to 60 %
  in summer. Fill happens in days in winter for leaky cases, so the summer
  value rarely matters for fill; it matters for first fog (§3.6).
- Weather is hourly TMY from the nearest NSRDB cell; RH accuracy in NSRDB
  is a few percent absolute.

### 3.3 Cold pane temperature (`engine/cavity.py`)

    T_cold = T_out + f (T_room − T_out) + solar − sky + vent

- f_cold is static: no thermal mass, no diurnal lag. A pane lags outdoor
  air by minutes, so this is fine hourly.
- Sun: α·I/h_out on the outer pane. Sky: ε σ F (T⁴ − T_sky⁴)/h_out with
  cloud correction. Vent coupling: two-stream upper bound (§3.1 of
  cavity.py docstring). None of these move fill time; sky decides whether
  and when the pane fogs (first fog 264 h with sky vs 5,830 h without at
  gasketed leakage).

### 3.4 Condensation and drying at the pane (`engine/moisture.py`)

- Air pinned at W_sat(T_cold) when supply exceeds it; condensation = the
  excess supply. Evaporation is instantaneous up to saturation: upper
  bound on drying, so reported film is a lower bound.
- Surface mass-transfer limit ignored. At natural convection
  h_m·ρ ≈ 0.009 kg/m²/s ≈ 22 g/m²/h of capacity against a supply of
  ~1 g/m²/h at 24 ACH. Not the bottleneck below several hundred ACH.
- Film cap 100 µm and visible threshold 5 µm are unmeasured (ANLY-002
  assumptions #4, #5). Affect visible-hour counts only.
- Ice saturation below 0 °C (both models). Correct for frost.

### 3.5 Desiccant (`engine/desiccant.py`)

    q_eq = q_max(T) · K(T)·RH / (1 + K(T)·RH);  dq/dt = (q_eq − q)/τ

- Constants fitted to published 3A curves: q_max 0.21 at 25 °C, K 60,
  0.5 %/K capacity loss, K halves every 23 K. Sensitivities in table
  rows 6, 7, 10. A vendor isotherm at three temperatures would remove
  most of this.
- No capacity credit below 25 °C (conservative, −, a few %).
- Desiccant temperature = cavity air temperature. In direct sun the
  cartridge can run hotter than the air; hot sieve holds less. Sign +,
  unquantified, summer only.
- τ is the least certain input (row 5). It encodes bead kinetics AND
  cartridge air access. A supplier can measure it; INOVUES can too with
  a scale and a humidity chamber.
- Uptake capped by what the air can deliver (supply-limited regime); the
  coupled step makes this exact.

### 3.6 End of life

- "Full" at 0.95 × q_max(25 °C). The sieve's equilibrium at 35 % RH is
  0.967 × q_max, so any threshold above ~0.96 never fires at typical room
  humidity. Stated in the UI. The rh_eq trace shows loss of protection
  independently of the threshold.
- First fog depends on sky cooling (§3.3) and room RH (row 9): 28 h at
  50 % RH, 284 h at 25 %. Present it as "first hour the pane fogs in this
  model" with the sky toggle visible next to it.

### 3.7 Numerics

- Exchange and condensation: closed form per hour (validated in ANLY-002
  and here against the analytic rate).
- Desiccant: quasi-steady coupled step, bisection to 1e-9, substeps ≥
  4/τ. Reference agreement ≤ 2.5 %.
- The desiccant-inactive fallback (cannot take water from supply-level
  air, desorption off) uses the plain exchange step. Correct by
  construction: the air is no longer a fast variable then.

## 3.8 Sealant vapour diffusion (added 2026-09-11)

    J = P . (perimeter x bead width) . dp_v / bead depth

- Permeabilities are ASTM E96 ranges, not product data (DOWSIL 795 does
  not publish WVT): silicone 20-40 g.mm/m2/day at 38 degC/90 % RH, PIB
  0.2-0.5. Uncertainty x2. Cavity taken as dry: upper bound.
- 1/4 x 1/4 in silicone bead, 60 x 96 in window, 70 degF / 35 % RH:
  0.035 g/day. With zero air leakage 1 kg of 3A lasts 6.6 years; PIB
  > 20 years. This is the physical floor the old IGU-grade preset was
  guessing at.
- The wet-sealed air-leakage preset (0.005 cfm/ft2) is the E283 detection
  floor, i.e. "not measurable by the standard test", not a measurement
  of an INOVUES seal. Between 0.005 and 0 the answer moves from 16 days
  to 6.6 years. Item 1 of section 4 (pressurisation test) resolves it.

## 4. What would tighten the numbers most, in order

1. A measured operating pressure across an installed SWR cavity (a
   micromanometer for a week). Collapses items 1, 2, 4.
2. A vendor 3A isotherm at 3 temperatures and a measured τ for the
   cartridge design. Collapses 5, 6, 7, 10.
3. Room RH logged over a year in one target building. Collapses 9.
4. A cavity RH logger next to a known desiccant mass for a month: the
   single experiment that validates the whole chain end to end.

## 5. Corrections made to earlier statements

- "Deeper cavities help linearly" (HANDOVER, Explain step 2): wrong for
  desiccant life; offset cancels. Corrected.
- "Desorption roughly doubles life at hermetic leakage" (checkpoint 1
  message): artefact of the stiffness bug. At hermetic leakage released
  water has nowhere to go; the toggle is nearly inert there.
- First-fog events in spring from desorption: artefact. Removed by the
  coupled step.

## 6. Corrections made 2026-09-15: the two layers were modelled in parallel

**What was wrong.** Section 3.1 derived a cavity ACH for each layer at the same fixed operating pressure (3 Pa plus wind on the outdoor path) and summed them, with both streams feeding the cavity every hour. That is two independent leaks in parallel. A two-layer assembly is two leaks in series: one signed pressure difference between room and outdoors, the cavity at a pressure in between, the same air through both layers, fed from the high-pressure side only. The audit's own row 1 ("largest single uncertainty: operating pressure") was pointing at the symptom; the structural error was the summing.

**Size of the error.** For equal layers each takes half the pressure, so series flow is C·(ΔP/2)^0.65 against parallel 2·C·ΔP^0.65: parallel is 2^1.65 = 3.1× too high. For a retrofit 60× tighter than the existing window (0.005 vs 0.30 cfm/ft²) parallel gave 45 ACH at 3 Pa where series gives 0.74 ACH: 60× too high, and attributed 98 % of the moisture to outdoor air when the tight retrofit was the only thing deciding the flow. On the 277 Park Ave fixture, 1000 g of 3A, the parallel model filled the sieve in under 0.05 yr; series gives 0.13 yr. Section 1 rows 1 and 4 and the last ASSUMPTIONS line in app.py described the parallel model and are superseded by this section.

**What replaced it (engine/pressure.py).**

    ΔP(h) = P_HVAC(h) + (ρ_out − ρ_in)·g·h_NPL − ½ρ v(h)² C_p(θ)      [Pa, room minus outdoors]
    q(h)  = |ΔP|^n / (C_out^(−1/n) + C_in^(−1/n))^n                    n = 0.65, C = AL·18.29/75^n
    ΔP > 0: q enters as room air;  ΔP < 0: q enters as outdoor air;  ΔP = 0: breathing only

- P_HVAC: +5 Pa weekdays 07 to 19, 0 Pa otherwise. Design range 5 to 25 Pa (ideal 12.5); field measurements in existing buildings 1 to 2 Pa; night setback ≈ 0. Parameter. ESTIMATE.
- Stack: neutral plane at mid-height (uniform leakage), h from floor and floor count. Parameter. ESTIMATE of the neutral plane.
- Wind: C_p from the angle between station wind direction and facade normal, table (0°: +0.60, 45°: +0.25, 90°: −0.50, 135°: −0.40, 180°: −0.30), face-averaged values for a rectangular building. Station wind at 10 m, no height or terrain correction. ESTIMATE. If the weather file has no wind direction (files cached before 2026-09-15), every windy hour is treated as windward, C_p = 0.6, which is conservative for outdoor-air ingress.
- Breathing: ACH = max(0, T_air(h−1) − T_air(h)) / T_air(h), split between the sides by flow coefficient. Ideal gas, no further assumption.
- Not modelled: gust pumping through one leaky layer with the other hermetic (ΔP/P_atm ≈ 1e-4 of the cavity volume per gust). Only matters below ~0.01 ACH. Listed for the hermetic case.

**Verification.** engine/pressure.py closed form checked against a 200-step bisection of C_out·x^n = C_in·(ΔP − x)^n (tests/test_pressure.py). Series run with constant +12 Pa, no wind, no stack reproduces the legacy engine fed with the same ACH on the room path only, to 1e-4 (tests/test_series_equivalence.py): the rework touched only how the ACH and its side are decided. Property tests: one side fed per hour; through-flow never exceeds the tighter layer alone at the full |ΔP|; tightening a layer never raises flow; a hermetic layer leaves breathing only; fed side follows the sign (tests/test_properties.py).

**Second correction, same day: the series model alone dropped single-sided exchange.** With one layer hermetic, through-flow is zero, but the other layer still exchanges air with its own side through its own cracks. The dominant mechanism is a buoyant loop: the cavity air differs in temperature from the side beyond the layer; the layer has cracks low and high; air of one density leaves at one end and the other comes in at the other. The old audit's "single-sided stack loop estimate" was a rough version of this and was lost in the first rework. Now in engine/pressure.py:

    dP_loop = |ρ_side − ρ_cavity| · g · k · H_window
    q_loop  = (C/2) · (dP_loop/2)^n_loop            k = 0.75, n_loop = 0.65, both parameters, ESTIMATES

k is the fraction of the window height between the average inlet and the average outlet of the loop (1 all at head and sill, 0.5 spread evenly, 0 all at one height). n_loop = 0.65 extrapolates the 75 Pa rating down to ~0.3 Pa with the same exponent; flow there is probably laminar (n → 1), which would give up to 6× less; 0.65 is the conservative choice for life. Loops are superposed on the through-flow (the standard practice; the interaction is second order). Cavity temperature for the loop is the previous hour's. Not modelled: gust pumping (ΔP/P_atm ≈ 1e-4 per gust) and the wind-pressure gradient over the face, both second order to the buoyant loop.

Verification: hand calculation of dP_loop and q_loop (tests/test_pressure.py); loops zero for a hermetic layer or k = 0, never negative, never lower the total exchange, shrink with k, grow with window height (tests/test_properties.py). The series-to-legacy equivalence test runs with loops off.

**Consequence for the product (corrected).** Sweep on the fixture (60×96×0.6 in, 1000 g 3A, mean ACH over the year as through-flow + loop out + loop in):

    old window  retrofit   through  loop_out  loop_in   total    1000 g full after
    0.30        0.005      0.65     3.52      0.07      4.24     0.02 yr (1 week)
    0.30        0.0        0.00     3.52      0         3.52     0.02 yr
    0.005       0.005      0.42     0.06      0.07      0.54     0.13 yr
    0.005       0.0        0.00     0.06      0         0.06     0.89 yr
    0.001       0.001      0.08     0.01      0.01      0.11     0.56 yr
    0.0         0.0        0.00     0         0         0.0006   6.3 yr (silicone diffusion floor)

A hermetic retrofit over an unsealed old window buys nothing: the old window's loop alone feeds the cavity 3.5 ACH of outdoor air. Both seals matter; the tighter layer sets the through-flow, each layer's own leakage sets its loop. Years require both layers well below the E283 floor, and then the silicone bead's vapour permeability (≈ 30 g/yr here) is the cap; PIB is 100× lower. The measurement that settles this is a cavity pressure-decay test on an installed unit, which gives the COMBINED leakage of both layers; a second test with the retrofit's vent taped separates them.

**Revised ranking (replaces §1 rows 1 and 4).**
1. Leakage of BOTH layers below the E283 floor: decides weeks vs years. Unmeasured.
2. Loop crack placement k and the sub-1 Pa exponent: ±factor 6 on the loop, which dominates in the near-hermetic case.
3. Sealant vapour permeability (silicone vs PIB): the floor once both are airtight. Published ranges only.
4. HVAC pressurisation and its schedule: decides room-fed vs outdoor-fed through-flow hours; ±factor 1.5 between 0 and 12 Pa.
5. C_p table and the missing height/terrain correction: ±factor 1.5 on windy-hour through-flow.
6. Neutral plane position: ±3 Pa on tall buildings.
