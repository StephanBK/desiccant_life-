// Thin client for the Flask API. Inputs live in one flat object in the UI
// and are sent as a query string, so a run is also a shareable URL.

// First-load inputs live in defaults.json so the engine's parity test
// (tests/test_parity.py) can read the very same file. Since 2026-09-23 they
// equal the 277 Park app's default scenario: VIG, both layers wet-sealed,
// 8 lb (3,628.739 g), 70 F / 30 %, north facade, floor 25 of 50, desorption
// on, one whole year simulated after the desiccant fills.
import DEFAULTS from './defaults.json'

export const DEFAULT_INPUTS = DEFAULTS

export function toQuery(inp, extra = {}) {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries({ ...inp, ...extra })) {
    if (v === '' || v === null || v === undefined) continue
    p.set(k, typeof v === 'boolean' ? (v ? '1' : '0') : String(v))
  }
  return p.toString()
}

async function get(path, query) {
  const r = await fetch(`${path}?${query}`)
  const body = await r.json().catch(() => ({ error: `HTTP ${r.status}` }))
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`)
  return body
}

export const api = {
  presets: () => get('/api/presets', ''),
  lifetime: (inp) => get('/api/lifetime', toQuery(inp)),
  sweep: (inp, axes) => get('/api/sweep', toQuery(inp, { ...axes, trace: 0 })),
  exportUrl: (inp) => `/api/export.xlsx?${toQuery(inp)}`,
}

export const fmt = {
  n: (x, d = 0) => (x === null || x === undefined ? 'n/a' : Number(x).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: 0 })),
  g: (x, sig = 3) => (x === null || x === undefined ? 'n/a' : Number(Number(x).toPrecision(sig)).toLocaleString('en-US', { maximumFractionDigits: 6 })),
  hours: (h) => {
    if (h === null || h === undefined) return null
    if (h < 48) return { v: h, u: 'hours' }
    if (h < 24 * 90) return { v: +(h / 24).toFixed(1), u: 'days' }
    if (h < 8760 * 1.5) return { v: +(h / 24 / 30.44).toFixed(1), u: 'months' }
    return { v: +(h / 8760).toFixed(2), u: 'years' }
  },
  clock: (hour) => {
    const d = Math.floor(hour / 24)
    const date = new Date(Date.UTC(2021, 0, 1 + d))
    const m = date.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' })
    return `${m} ${date.getUTCDate()}, ${String(hour % 24).padStart(2, '0')}:00`
  },
}

// Mirror of engine/leakage.py so the rail can show the derived ACH live.
export function achFromAL(alCfmFt2, dpPa, offsetIn) {
  const offsetM = offsetIn * 0.0254
  if (!(offsetM > 0)) return NaN
  return alCfmFt2 * 18.29 * Math.pow(dpPa / 75, 0.65) / offsetM
}
