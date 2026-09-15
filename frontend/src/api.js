// Thin client for the Flask API. Inputs live in one flat object in the UI
// and are sent as a query string, so a run is also a shareable URL.

export const DEFAULT_INPUTS = {
  address: '277 Park Avenue, New York, NY',
  orientation: 'south',
  width_in: 60, height_in: 96, offset_in: 0.6,
  f_cold: 0.30, u_ip: 0.30, r_ip: 0.97, f_warm: '',
  t_in: 70, rh_in: 35,
  al_out: 'wet_sealed', al_in: 'wet_sealed', dp_pa: 3,
  p_occ_pa: 5, p_unocc_pa: 0, occ_start_h: 7, occ_end_h: 19, weekdays_only: true,
  floors: 10, window_floor: 5, floor_height_ft: 11.81, series_model: true, breathing: true,
  sealant_out: 'silicone', sealant_in: 'silicone', bead_width_in: 0.25, bead_depth_in: 0.25,
  wind_scaling: true,
  grams: 1000, desiccant: 'ms3a', tau_h: '',
  desorption: false, full_fraction: 0.95,
  pane_coupling: true, absorptance: 0.10, sky_radiation: true,
  max_years: 20, visible_um: 5,
}

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
