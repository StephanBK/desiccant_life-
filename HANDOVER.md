# HANDOVER — Desiccant Lifetime Simulator (ANLY-003)

Last session: 2026-09-23 (session 7, parity with the 277 Park app). Before that 2026-09-15 (session 4). State: v0.5 (series pressure
model + single-sided loops) pushed: main on GitHub at 2748f2b + the
tab-consistency commit after it, Railway serves it.

## Session 7 (2026-09-23): parity with the 277 Park app

- Stephan: the old simulator (this app, embedded in Odoo) and the 277 Park
  app (StephanBK/park277-desiccant) share the engine but showed different
  results. PROVEN on the live API: identical inputs give byte-identical
  headline, years and fog map. The differences were the old app's own:
  (1) starting inputs (address without ZIP geocoded to 277 Park Avenue,
  BROOKLYN 11205; south facade; f 0.30 / U 0.30; RH 35 %; floors 10/5;
  1,000 g; desorption off), (2) runs stopped in the fill year, so the
  winter after saturation was never simulated, (3) "first fog" meant the
  first trace of liquid (hour 0 for the 277 default), not visible fog.
- FIX: first-load inputs moved to frontend/src/defaults.json and set to the
  277 default (VIG f 0.014, U 0.16, north, floor 25 of 50, 3,628.739 g =
  8 lb, 70 F / 30 %, desorption on, years_after_full 1). API default
  address now has the ZIP. "First fog" everywhere (Simulate card, chart
  marker, Cinema, Sweep) = first VISIBLE fog; first trace of liquid kept on
  Explain. New card and headline field fog_days_per_year = days with visible
  fog in the last simulated year (YearSummary.days_visible), the 277 app's
  definition. Sweep and Excel export accept years_after_full; sweep points
  carry first_visible_hour and fog_days_per_year.
- tests/test_parity.py (7): fog-day counting, headline field, sweep and
  export, ZIP default, defaults.json == the 277 request, and the old app's
  first-load request gives identical results to the 277 app's. The 277 repo
  pins the same request from its side (test/engine.test.js "parity").
- Anomalies Stephan reported, investigated (no engine change): fog in May
  and June at high room RH in tight cavities is the WINTER FILM DRYING
  (wet seals trap it; cavity air holds ~0.4 g/m2), single-film model puts
  it on the old pane where in summer it would move to the colder retrofit
  glass; isolated spring-night fog with leaky outer seals is radiative dew
  (pane ~7 F below outdoor air on clear nights). "No fog end of year 1,
  fog right at the start of year 2" NOT reproduced (60 scenario-years,
  TMY continuous at the boundary, state carried): waiting for the exact
  scenario link.
- Next (Stephan chose "both"): one front end later (277 app plus an
  Advanced mode with this app's inputs), so the two cannot drift.

## Session 6 (2026-09-23): air relaxation fix (post-saturation fog was inflated)

- Found via the 277 Park app: 4 lb showed more fog than no desiccant. Part
  was the app (0 lb reported its start-up year); the rest was the engine.
- BUG: coupled_substep put the cavity air at its balance humidity W*
  instantly. Right for a hungry sieve (seconds), wrong for a full or tiny
  one: the air then lags at the exchange rate for hours (as step_hour
  does). The jump skipped the lead-in before condensation. 0.001 g gave
  700 fog h/yr vs 400 at 0 g; a full 4 lb sieve without desorption 745.
  The old "inactive desiccant" guard missed nearly-full sieves.
- FIX: the air relaxes toward W* at lam = (a.m_cav + dD/dW)/m_cav,
  re-linearised over RELAX_STEPS = 8 micro-steps per substep, never past
  W*, pinned at pane saturation while condensing or while a film feeds it;
  water balance exact per step (uptake is the residual). Hungry sieve:
  unchanged (lam huge). After: 0.001 g 368 h (condensate within 0.4 %,
  film within 1.8 % of 0 g), 4 lb desorption off 296 (below 0 g), 4 lb
  desorption on 57, 8 lb desorption on 87 (test weather, year after full).
  About 3.1 s per simulated year (was ~1.9).
- Found in the new code and fixed: a film of 6e-323 kg (denormal) made the
  loop evaporate it forever; films below FILM_ZERO_KG = 1e-15 are zero, and
  a pass cap with a water-conserving safety net (RELAX_STATS counts it;
  tests assert zero on real runs).
- Tests: tests/test_relaxation.py (6). Three existing tests adjusted, each
  proven first: cross-check now runs without sealant diffusion like its
  reference (the 'sealed' case had passed because +2.5 % solver error and
  -5 % diffusion cancelled; now -0.4 %); offset property skips cases where
  the deeper cavity's extra trapped air water is >= 5 % of capacity (that
  water is now conserved, the old step discarded it); sealed-cavity
  invariant allows the phantom water below.
- KNOWN SIMPLIFICATION (pre-existing, now visible): m_cav is recomputed
  hourly from temperature at fixed W, so the air's water changes at hour
  boundaries (1 g sieve, 1 ft2 sealed: 0.0017 g/yr, matched the balance
  gap to 6 decimals). 277 Park window: ~0.07 g/yr, ~0.01 % of 8 lb
  capacity. Kept for byte-equivalence with cavity_moisture at 0 g.
- The humidifier effect of desorption is far smaller than the pre-fix
  numbers suggested; the no-cold-credit question still stands but matters
  much less.

## Session 5 (2026-09-23): opt-in fog map for the 277 Park app

- New sister app INOVUES-APPS/park277-desiccant (stakeholder-facing,
  few controls) calls this API through its own server-side proxy.
- /api/lifetime opt-in parameters, absent = original behaviour (tested):
  fog_map=1 adds payload["fog"]: one string per simulated year of 8,760
  digits, '0' clear, '1'..'9' visible-fog intensity log-spaced from
  visible_um (5) to the retained-film cap (100 um), null for a year with
  no visible hour. years_after_full=N (0..5) simulates N whole years
  after the fill year. headline gains first_visible_hour/_days (film
  above the visible threshold, not any liquid). tests/test_fog_map.py.
- FINDING: the room parameters are t_in and rh_in. The Sep 16 study sent
  rh_in_pct=30, which the API ignored: those runs used the 35 % default.
- FINDING: with desorption on, a sieve near 99 % full holds the cavity at
  its equilibrium RH (78 % at 0 degC, 91 % at 5 degC) and releases stored
  water; VIG (f 0.014), wet-sealed both, 8 lb, 70 F / 30 %: full day 164,
  886 h of thin visible film (5-7 um) in Feb-Mar of year 2. Desorption off
  or no desiccant: none. Sensitive to the no-credit-below-25 degC capacity
  cap: a few percent of real cold capacity would drop that RH to ~20 %.
  Vendor isotherm at 0-10 degC would settle it.

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

## Session 4 (2026-09-16) summary

- Study runs for 277 Park (3 retrofit glasses x 3 seal scenarios, 3,770 g
  3A; then 3 glasses x 2 retrofit seals x 3 existing-window seals at 0 g)
  drove the correction below. Figures and scripts live outside the repo
  (Stephan's downloads: 277Park_desiccant_study.pdf, 277Park_no_desiccant_study.pdf,
  figs.py, figs_nodes.py).
- Engine: sealant bead diffusion made signed and two-sided (AUDIT 3.9).
  New: HourTables.ach_diff_out / ach_diff_in, split_exchange_net().
  Old fixed j_diff path retired (coupled_substep still accepts j_diff=0).
- Tests: two new (four-way split signs; beads alone cannot push the cavity
  above its wetter neighbour on film-free hours). Four pre-existing
  hypothesis edges fixed in the tests, each verified to fail identically on
  the old engine: 6 h floors for gram-scale sieves (x2), loop-vs-k check
  reduced to first hour plus annual total, and the never-fills-at-higher-flow
  equilibrium artifact skipped with assume(). Sealed-cavity invariant now
  "net bead flux <= dry-cavity bound" instead of ">= 0". 312 tests.
- Findings worth carrying: without desiccant, visible fog needs a way in
  (wet-sealed retrofit passing ~0.5 ACH of room air under HVAC +5 Pa) and
  no way out (old window 0.1 cfm/ft2 or tighter); a hermetic retrofit or a
  leaky old window each prevent it. Glass type matters only without
  desiccant (VIG coldest pane, worst). With desiccant the sieve loses control
  of the dew point at ~60 % loading, before the 95 % "full" mark.
- Open engine items: run N years past saturation (scenario C's later
  winters were never simulated); "dew-point control lost" as a headline
  metric; price per kg input for $/yr of protection.

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
