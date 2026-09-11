import { useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmt } from './api.js'

// User-unit labels for each sweepable engine key.
const AXES = {
  desiccant_grams: { label: 'Desiccant mass', unit: 'g', from: 10, to: 1000, log: true },
  ach_out: { label: 'Outdoor leakage', unit: 'ACH', from: 0.002, to: 20, log: true },
  ach_in: { label: 'Room-side vent', unit: 'ACH', from: 0.005, to: 20, log: true },
  rh_room: { label: 'Room RH', unit: '%', from: 20, to: 60, log: false },
  t_room_c: { label: 'Room temperature', unit: '°F', from: 62, to: 78, log: false },
  width_m: { label: 'Cavity width', unit: 'in', from: 24, to: 120, log: false },
  height_m: { label: 'Cavity height', unit: 'in', from: 36, to: 144, log: false },
  offset_m: { label: 'Cavity offset', unit: 'in', from: 0.25, to: 4, log: true },
  tau_hours: { label: 'Sieve time constant', unit: 'h', from: 0.25, to: 24, log: true },
}

function range(from, to, n, log) {
  const out = []
  for (let i = 0; i < n; i++) {
    const t = n === 1 ? 0 : i / (n - 1)
    const v = log ? Math.exp(Math.log(from) + t * (Math.log(to) - Math.log(from))) : from + t * (to - from)
    out.push(+v.toPrecision(3))
  }
  return out
}

function AxisRow({ title, ax, setAx, allowNone }) {
  const meta = AXES[ax.key] || {}
  const pick = (k) => setAx(k === 'none' ? { key: 'none' } : { key: k, from: AXES[k].from, to: AXES[k].to, n: ax.n || 8, log: AXES[k].log })
  return (
    <div className="axis-row">
      <div><label>{title}</label>
        <select value={ax.key} onChange={(e) => pick(e.target.value)}>
          {allowNone && <option value="none">none (1-D)</option>}
          {Object.entries(AXES).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
        </select></div>
      {ax.key !== 'none' && <>
        <div><label>From ({meta.unit})</label><input type="number" value={ax.from} onChange={(e) => setAx({ ...ax, from: Number(e.target.value) })} /></div>
        <div><label>To ({meta.unit})</label><input type="number" value={ax.to} onChange={(e) => setAx({ ...ax, to: Number(e.target.value) })} /></div>
        <div><label>Points</label><input type="number" min="2" max="20" value={ax.n} onChange={(e) => setAx({ ...ax, n: Number(e.target.value) })} /></div>
        <div><label>Spacing</label><select value={ax.log ? 'log' : 'lin'} onChange={(e) => setAx({ ...ax, log: e.target.value === 'log' })}><option value="log">log</option><option value="lin">linear</option></select></div>
      </>}
    </div>
  )
}

const days = (h) => (h === null ? null : h / 24)

function colorFor(d, dmin, dmax) {
  if (d === null) return '#1f5fa8'
  const t = dmax === dmin ? 0.5 : (Math.log(d + 1) - Math.log(dmin + 1)) / (Math.log(dmax + 1) - Math.log(dmin + 1))
  // sand (short) -> teal -> glass blue (long)
  const stops = [[243, 232, 210], [201, 156, 85], [31, 158, 154], [31, 95, 168]]
  const s = Math.min(2.999, t * 3), i = Math.floor(s), f = s - i
  const c = stops[i].map((a, k) => Math.round(a + (stops[i + 1][k] - a) * f))
  return `rgb(${c.join(',')})`
}

function Heat({ res }) {
  const cells = res.grid.flat().map((p) => days(p.exhausted_hour)).filter((d) => d !== null)
  const dmin = Math.min(...cells, 1), dmax = Math.max(...cells, 2)
  const nx = res.x_values.length, ny = res.y_values.length
  const mx = AXES[res.x_key], my = AXES[res.y_key]
  const label = (d, p) => d === null ? `>${p.years_run}y` : d < 2 ? `${(d * 24).toFixed(0)}h` : d < 90 ? `${d.toFixed(0)}d` : d < 540 ? `${(d / 30.44).toFixed(1)}mo` : `${(d / 365).toFixed(1)}y`
  return (
    <>
      <div className="heat" style={{ gridTemplateColumns: `90px repeat(${nx}, 1fr)` }}>
        {[...res.grid].reverse().map((row, ri) => {
          const iy = ny - 1 - ri
          return [
            <div key={`y${iy}`} className="ylab">{fmt.g(res.y_values[iy])} {my.unit}</div>,
            ...row.map((p, ix) => {
              const d = days(p.exhausted_hour)
              const bg = colorFor(d, dmin, dmax)
              const dark = d === null || (d > (dmin + dmax) / 4)
              return <div key={`${ix}-${iy}`} className="cell" style={{ background: bg, color: dark ? '#fff' : '#16233a' }}
                title={`${mx.label} ${p.x} ${mx.unit}, ${my.label} ${p.y} ${my.unit}: ${d === null ? 'not exhausted' : `${fmt.n(p.exhausted_hour)} h`}; first fog ${p.first_condensation_days ?? 'none'} d; ${p.hours_per_gram ?? '—'} h/g`}>{label(d, p)}</div>
            }),
          ]
        })}
        <div />
        {res.x_values.map((x) => <div key={x} className="xlab">{fmt.g(x)}</div>)}
      </div>
      <div className="legend"><span>short</span><span className="bar" /><span>long</span><span style={{ marginLeft: 12 }}>x: {mx.label} ({mx.unit}) · y: {my.label} ({my.unit}) · cell = time until the sieve is full</span></div>
    </>
  )
}

function Line1D({ res }) {
  const mx = AXES[res.x_key]
  const data = res.points.map((p) => ({ x: p.x, full: days(p.exhausted_hour), fog: days(p.first_condensation_hour), hpg: p.hours_per_gram }))
  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
        <CartesianGrid stroke="#e8edf2" />
        <XAxis dataKey="x" type="number" scale={mx.log ? 'log' : 'linear'} domain={['dataMin', 'dataMax']} fontSize={11} label={{ value: `${mx.label} (${mx.unit})`, position: 'insideBottom', offset: -4, fontSize: 11 }} />
        <YAxis yAxisId="d" scale="log" domain={['auto', 'auto']} fontSize={11} width={48} label={{ value: 'days', angle: -90, position: 'insideLeft', fontSize: 11 }} />
        <YAxis yAxisId="g" orientation="right" fontSize={11} width={48} label={{ value: 'h per g', angle: 90, position: 'insideRight', fontSize: 11 }} />
        <Tooltip formatter={(v, k) => [v === null ? 'none' : fmt.n(v, 2), k]} labelFormatter={(x) => `${mx.label} ${x} ${mx.unit}`} />
        <Legend iconType="plainline" />
        <Line yAxisId="d" dataKey="full" name="days until sieve is full" stroke="#9a7330" strokeWidth={2.5} isAnimationActive={false} />
        <Line yAxisId="d" dataKey="fog" name="days until first fog" stroke="#d0642f" strokeWidth={2} strokeDasharray="5 3" isAnimationActive={false} />
        <Line yAxisId="g" dataKey="hpg" name="hours per gram" stroke="#1f5fa8" strokeWidth={1.5} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function Sweep({ inp }) {
  const [x, setX] = useState({ key: 'desiccant_grams', from: 10, to: 1000, n: 8, log: true })
  const [y, setY] = useState({ key: 'ach_out', from: 0.002, to: 20, n: 6, log: true })
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function go() {
    setBusy(true); setErr(null)
    const axes = { x_key: x.key, x_values: range(x.from, x.to, x.n, x.log).join(',') }
    if (y.key !== 'none') { axes.y_key = y.key; axes.y_values = range(y.from, y.to, y.n, y.log).join(',') }
    try { setRes(await api.sweep(inp, axes)) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const points = x.n * (y.key === 'none' ? 1 : y.n)
  return (
    <>
      <div className="card">
        <h2>Sweep</h2>
        <p className="lede">Every other input stays as set in the rail. Each point is a full lifetime run, capped at 5 years, so a big grid takes a minute.</p>
        <AxisRow title="Across" ax={x} setAx={setX} />
        <AxisRow title="Down" ax={y} setAx={setY} allowNone />
        <button className="btn primary" onClick={go} disabled={busy || points > 400}>{busy ? `Running ${points} points…` : `Run ${points} points`}</button>
        {points > 400 && <span className="hint" style={{ marginLeft: 12 }}>Keep it under 400 points.</span>}
        {err && <div className="status err" style={{ marginTop: 12 }}>{err}</div>}
      </div>
      {res && (
        <div className="card">
          <h2>{res.mode === '2d' ? 'Time until the sieve is full' : `Lifetime against ${AXES[res.x_key].label.toLowerCase()}`}</h2>
          {res.mode === '2d' ? <Heat res={res} /> : <Line1D res={res} />}
        </div>
      )}
    </>
  )
}
