# HANDOVER — Desiccant Lifetime Simulator (ANLY-003)

Last session: 2026-09-11. State: v0.1.0 built and verified locally, not yet
deployed.

## Where things stand

- Engine, API, frontend all in this repo. 237 tests pass.
- Frontend is built and committed in `static/dist`, so Railway builds
  with Nixpacks (Python only) and serves it. Rebuild with
  `cd frontend && npm run build` after any frontend change and commit
  the result.
- Default scenario on first load (decided 2026-09-10): outdoor
  "sealed" 0.02 ACH (freshly resealed old facade), room "sealed"
  0.1 ACH (tight retrofit), 50 g 3A, 277 Park, 60 x 96 x 0.6 in.

## Deploy to Railway (first time)

1. Push this repo to `StephanBK/desiccant_life` (main).
2. Railway: new project from repo. Nixpacks detects Python.
3. Variables: `NREL_API_KEY`, `MAPBOX_TOKEN`. Optional
   `WEATHER_CACHE_DIR` if the engine's weather cache should persist
   (see engine/weather.py).
4. Healthcheck path `/api/health` is in railway.json.

## Decisions log

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
Desiccant is an IGU-grade-seal technology. The 2-D sweep (mass x
retrofit leakage) shows where it flips; deeper cavities help linearly.

## Backlog

- Vendor 3A data sheet to replace the fitted isotherm; add 4A, silica
  gel, CaCl2 rows.
- Odoo wrapper (zip + icon) once Railway is stable.
- Cavity animation: optional day/night sky and sun overlay.
- Sweep: export grid to Excel; save/share sweep URLs.
- Dev: code-split the bundle (647 kB) if load time matters on mobile.
- Consider persisting the NSRDB cache on a Railway volume.

## Conventions

- SI inside the engine, US customary at the API boundary and UI.
- Every estimate carries an ESTIMATE label in code and UI.
- Tests pin the numbers the Explain page quotes.
- Patches: git format-patch, verified on a fresh clone with the full
  suite, never whole-file replacements.
