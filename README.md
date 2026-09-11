# Desiccant Lifetime Simulator

INOVUES · Doc ID ANLY-003 · Owner: Stephan Ketterer, VP of Operations

How long does a given mass of desiccant last in a secondary-window cavity,
under real weather, with leakage from outdoors and a vent to the room?
And how many hours of protection does each gram buy?

Live: deployed on Railway (see HANDOVER.md). Local: see below.

## What it does

- Pulls a typical meteorological year (NSRDB) for any address.
- Models the cavity hour by hour: two air streams (outdoor leakage,
  room-side vent), the existing pane's temperature (sun, clear-sky
  cooling, vent warming), condensation and drying on that pane, and a
  3A molecular-sieve desiccant that follows its isotherm.
- Plays the year on repeat until the sieve is full; reports hours until
  full, hours until the pane first fogs, and hours per gram.
- Sweeps any input (mass, both ACH, room T/RH, cavity W/H/offset, time
  constant) in 1-D or as a 2-D heat map.
- Explains every step with its formula and the live numbers.
- Exports the run to Excel.

Physics engine inherited from `StephanBK/cavity_moisture` (ANLY-002) and
extended; see `engine/desiccant.py`, `engine/lifetime.py`, `engine/sweep.py`.

## Layout

```
app.py             Flask API + serves static/dist
engine/            all physics, SI throughout
frontend/          React + Vite source (builds into static/dist)
static/dist/       built frontend, committed so Railway needs only Python
tests/             pytest, 237 tests, uses the 277 Park TMY fixture
```

## Run locally

```
python3 -m pip install -r requirements.txt
export NREL_API_KEY=...   MAPBOX_TOKEN=...
python3 app.py                      # http://127.0.0.1:5000
```

Frontend development with hot reload:

```
cd frontend && npm install && npm run dev     # proxies /api to :5000
npm run build                                 # writes static/dist
```

Tests: `python3 -m pytest -q`.

## Every estimate, in one place

See the Explain page in the app, or `ASSUMPTIONS` in `app.py`.
