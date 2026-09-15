# HANDOVER — Desiccant Lifetime Simulator (ANLY-003)

Last session: 2026-09-15 (session 4). State: v0.5 (series pressure
model) committed locally on top of cefd881; main on GitHub is at
cefd881 and Railway serves that. v0.5 not yet pushed: Stephan pushes
with his PAT from the patch bundle.

## Session 4 (2026-09-15): the two layers were in parallel; now in series

- Concern raised: "ACH is everything; is it from 75 Pa?" The 75 Pa was
  already scaled to 3 Pa, but the two layers were summed as
  independent leaks at the same pressure (parallel). Real assembly is
  series: one signed room-to-outdoor dP per hour, tighter layer sets
  the flow, cavity fed from the high-pressure side. AUDIT.md §6.
- New engine/pressure.py: HVAC schedule (+5 Pa weekdays 07 to 19, 0
  otherwise), stack from floor position (NPL at mid-height), wind by
  direction vs facade (Cp table), series closed form, breathing.
  Weather now fetches NSRDB wind_direction; cached years without it
  are refetched (engine/weather.py _cache_read).
- Legacy parallel model kept behind series_model=false and for bare
  ACH inputs; cross-check and 0 g equivalence tests run on that path
  and still pass. New tests/test_series_equivalence.py ties series to
  legacy exactly at constant dP.
- Stephan then asked whether outdoors still exchanges air with the
  cavity through the old window alone. It does (buoyant loop through
  one layer's own cracks; the old audit's "single-sided stack loop"
  that the first rework dropped). Added: loops per layer, dP_loop =
  |rho_side - rho_cav| g k H, k = 0.75 and n = 0.65 as parameters
  (loops, loop_k, loop_n in the API). Both seals matter now.
- FINDING (corrected): unsealed old window + hermetic retrofit = 1
  week (3.5 ACH loop through the old window). Both at E283 floor 0.13
  yr; old at floor + retrofit hermetic 0.89 yr; both hermetic 6.3 yr
  (silicone diffusion floor). Leakage of BOTH layers below the floor is
  THE unknown; cavity pressure-decay test on an installed unit (plus a
  second with the vent taped) is the measurement. "Hermetic,
  IGU-grade" (0.0) preset brackets it with "Wet-sealed" (0.005).
- Property test slack for "more leakage never lengthens life" widened
  to one desiccant time constant (1 g sieve filling in 11 h).
- Open: gust pumping not modelled (only matters below ~0.01 ACH); Cp
  height/terrain correction; a customer-facing readout of "which
  measurement would settle this".

## Where things stand

- Engine, API, frontend all in this repo. 261 tests: 243 unit/API,
  5 engine-vs-reference cross-checks, 13 hypothesis property tests
  (40 random examples each). Full suite ~2.5 min; run the properties
  and cross-check separately if the 300 s CI limit bites.
- Frontend is built and committed in `static/dist`, so Railway builds
  with Nixpacks (Python only) and serves it. Rebuild with
  `cd frontend && npm run build` after any frontend change and commit
  the result.
- Default scenario on first load (decided 2026-09-10): outdoor
  "sealed" 0.02 ACH (freshly resealed old facade), room "sealed"
  0.1 ACH (tight retrofit), 1,000 g 3A (raised from 50 g on
  2026-09-11 so the first impression is not "hours"), 277 Park, 60 x 96 x 0.6 in.

## Deploy to Railway (first time)

1. Push this repo to `StephanBK/desiccant_life` (main).
2. Railway: new project from repo. Nixpacks detects Python.
3. Variables: `NREL_API_KEY`, `MAPBOX_TOKEN`. Optional
   `WEATHER_CACHE_DIR` if the engine's weather cache should persist
   (see engine/weather.py).
4. Healthcheck path `/api/health` is in railway.json.

## Session 2 (2026-09-11) summary

Order agreed: units/ladders, AERC leakage switch, audit + cross-check,
property tests, rail + tooltips, cinematic tab. All done. See AUDIT.md.
- Watch tab (Cinema.jsx): dark stage, vessel of 240 beads filling day by
  day over the whole run, saturation gauge, outdoor and pane cues, the
  two milestones, first-fog flash, timeline with markers, fullscreen.
  Auto-plays on opening the tab. Logo: frontend/public/inovues-logo.png
  (mark + wordmark split into inovues-mark.png / inovues-wordmark.png);
  brand teal #138fa3 is --water / --brand in index.css.
- Tooltips: engineering register (decision 2026-09-11), inputs and outputs.
- Rail closed on first load with a summary strip.

## Session 3 (2026-09-14) summary

Water-source accounting and the no-desiccant equivalence check.
- engine/lifetime.py: coupled_substep returns the net vent water of the
  step; split_vent_net splits it exactly into outdoor and room parts
  (N = ACH . m_air . (W_path - W_op) . dt, signed: negative = that path
  carried water OUT). YearSummary and LifetimeResult carry net_outdoor_g,
  net_room_g, net_diffusion_g; LifetimeResult also life_* (to the hour
  the sieve is full: the headline) and YearSummary heating_* (Oct-Mar).
  contribution_shares gives signed percentages of the net total (None
  when the total is not positive).
- API: payload["contributions"] = {life, run, life_hours}; year rows carry
  the new fields; Excel Summary and Years sheets extended.
- UI: summary strip ("water from room 52 % . outdoor 48 %"), a
  "Where the water came from" card under the headline (bar + legend;
  removals shown in words, not negative widths), Explain step 7 with the
  formulas and a live figure, year table columns.
- tests/test_contributions.py: run_lifetime at 0 g vs the original
  engine.moisture.run_year (byte-identical to cavity_moisture): identical
  condensing hours, yearly condensed within 2 % (0.2 % room-dominated),
  hourly W_cav exact except a handful of film-runs-out hours; the
  differences are the stream temperature, m_cav at room vs cavity
  humidity, and the starting state (spin-up off). Plus: split exactness,
  signed shares, heating-season calendar, life balance = uptake, winter
  outdoor net < 0 at 0 g with a loose existing window, fresh sieve takes
  from both paths.

## Decisions log

- 2026-09-14: contributions are NET (signed), not gross; sealant
  diffusion is its own third slice; headline split is over the sieve's
  life (the aftermath year would otherwise bury the fill: thousands of
  grams pass through an inactive sieve); no hourly split, but a heating
  season (Oct-Mar) split per year because at 0 g the full-year nets
  nearly cancel and hide winter drying. Presets unchanged.

- 2026-09-11 (late): INOVUES practice is wet-seal the existing window,
  then a wet-sealed retrofit. Presets now start at "wet_sealed" 0.005
  cfm/ft2 (ASTM E283 detection floor, ESTIMATE) on both ladders; the
  hypothetical IGU-grade preset is gone. Sealant vapour diffusion added
  (engine/leakage.py SEALANTS, silicone DOWSIL-795 class default, PIB
  option, 1/4 x 1/4 in bead): 0.035 g/day room side, the floor when air
  leakage is zero (1 kg lasts ~6.6 yr silicone, > 20 yr PIB).
  At the detection floor 1 kg lasts ~16 days. The measurement that
  decides which end of that range the real seal sits at: pressurise an
  installed cavity through a port and read the flow at 3-10 Pa.

- 2026-09-11: leakage inputs are rated air leakage (cfm/ft2 at 75 Pa,
  AERC / ASTM E283) plus an operating pressure (default 3 Pa); cavity ACH
  is derived (engine/leakage.py). Presets reference AERC: baseline
  single-pane 2.0, best certified insert 0.06 (Alpen WinSert). Raw ACH
  remains an API override (ach_out=, ach_in=). Wind now enters as
  pressure (0.5 rho v^2 Cp) on the outdoor path.
- 2026-09-11: headline numbers share one unit, months/years toggle.

- Only 3A molecular sieve in the library for now; dataclass is general.
- Desiccant uptake is first-order with tau default 2 h (input).
- Desorption (giving water back when hot and dry) is a toggle, default off.
- "Full" = 95 % of 25 degC capacity (input `full_fraction`); the
  desiccant's equilibrium RH is reported so loss of protection is visible
  before that.
- Outdoor ACH scales with wind (v^1.3, floor 0.3), toggle default on.
- No capacity credit below 25 degC (conservative).
- Pane warming from vent air: two-stream upper bound.
- Grams are per window; engine works per m2 of glass (divided by area).
- The run always finishes the year in which exhaustion occurs.

## Key finding so far (277 Park, 60x96x0.6 in, 50 g 3A)

AERC-converted leakage (3 Pa, 0.6 in cavity): baseline single-pane
window ~230 ACH, best certified insert ~9 ACH. Default scenario
(resealed 0.10 / best insert 0.06): 50 g full in 11 h, 0.22 h/g,
~40 kg for a year. Earlier ACH ladders (0.02 / 0.1 "sealed") were two
orders of magnitude tighter than any certified product; see audit.
Desiccant is an IGU-grade-seal technology, and BOTH layers must be
tight: a resealed existing window (0.10) alone fills 500 g in a day.
Cavity offset does not change fill time (crack flow per m2 is fixed;
deeper cavity = lower ACH but more air). See AUDIT.md for the ranked
error budget and the cross-check.

## Backlog

- Measurements that would tighten the model most: AUDIT.md section 4.

- Vendor 3A data sheet to replace the fitted isotherm; add 4A, silica
  gel, CaCl2 rows.
- Odoo wrapper (zip + icon) once Railway is stable.
- Cavity animation: optional day/night sky and sun overlay.
- Sweep: export grid to Excel; save/share sweep URLs.
- Dev: code-split the bundle (647 kB) if load time matters on mobile.
- Consider persisting the NSRDB cache on a Railway volume.

## Conventions

- Any physics change: rerun `python xcheck.py` style matrix (AUDIT.md
  section 2) and update the table.
- Property tests found three real edge cases and two invariants that
  were stated too strongly (see docstrings in tests/test_properties.py).

- SI inside the engine, US customary at the API boundary and UI.
- Every estimate carries an ESTIMATE label in code and UI.
- Tests pin the numbers the Explain page quotes.
- Patches: git format-patch, verified on a fresh clone with the full
  suite, never whole-file replacements.
