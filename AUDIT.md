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
