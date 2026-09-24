import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import Cavity from './Cavity.jsx'
import { fmt } from './api.js'
import { Tip } from './Tip.jsx'
import { SourceCard } from './Sources.jsx'

const C = { glass: '#1f5fa8', water: '#1f9e9a', fog: '#d0642f', sand: '#9a7330', cold: '#6e8fb5', ink3: '#8592a6' }

function Row({ label, value, color, tip }) {
  return (
    <div className="row">
      <span>{color && <i className="dot" style={{ background: color }} />}{label}</span>
      <b>{value}</b>
      {tip && <Tip id={tip} />}
    </div>
  )
}

function Stat({ cls, value, unit, label, sub, tip }) {
  return (
    <div className={`stat ${cls}`}>
      <div className="value">{value}{unit && <small>{unit}</small>}</div>
      <div className="label">{label}{tip && <Tip id={tip} inline />}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

function Headline({ h, inputs, unit, setUnit }) {
  const div = unit === 'years' ? 8760 : 730.5
  const show = (hours) => hours === null ? null : fmt.n(hours / div, hours / div < 10 ? 2 : 1)
  // 'First fog' = first VISIBLE film (5 um), as in the 277 Park app (2026-09-23);
  // the first trace of liquid is kept on the Explain tab.
  const ex = show(h.exhausted_hour), fc = show(h.first_visible_hour)
  const fogDays = h.fog_days_per_year ?? 0
  return (
    <>
    <div className="unit-row"><span className="hint">Show durations in</span><div className="unit-toggle" role="group" aria-label="Time unit">
        {['months', 'years'].map((u) => <button key={u} className="btn small" aria-pressed={unit === u} onClick={() => setUnit(u)}>{u}</button>)}
      </div></div>
    <div className="headline">
      <Stat cls="sand" tip="out_full"
        value={ex ?? (h.capped ? `> ${fmt.n(h.years_run * 8760 / div, 0)}` : 'never')}
        unit={unit}
        label={`${fmt.n(inputs.grams)} g of ${inputs.desiccant === 'ms3a' ? '3A sieve' : inputs.desiccant} lasts`}
        sub={ex ? `full after ${fmt.n(h.exhausted_hour)} hours (${fmt.n(h.exhausted_hour / 24, 1)} days); holds ${fmt.n(inputs.capacity_g, 1)} g of water` : `run capped at ${h.years_run} years, loading ${h.final_loading_pct_of_max}%`} />
      <Stat cls="fog" tip="out_fog"
        value={fc ?? 'none'}
        unit={fc ? unit : ''}
        label="until the pane first fogs (visible film)"
        sub={fc ? `hour ${fmt.n(h.first_visible_hour)} (${fmt.n(h.first_visible_hour / 24, 1)} days), ${fmt.clock(h.first_visible_hour % 8760)}, year ${Math.floor(h.first_visible_hour / 8760) + 1}` : `no visible fog in ${h.years_run} year${h.years_run > 1 ? 's' : ''}`} />
      <Stat cls="fog" tip="out_fogdays"
        value={fmt.n(fogDays)}
        unit={fogDays === 1 ? 'day' : 'days'}
        label={h.exhausted_hour !== null ? 'with fog per year once full' : 'with fog per year'}
        sub={`year ${h.years_run}${h.exhausted_hour !== null ? ', the first full year after the desiccant fills' : ''}`} />
      <Stat cls="glass" tip="out_hpg"
        value={h.hours_per_gram !== null ? fmt.n(h.hours_per_gram, h.hours_per_gram < 10 ? 2 : 0) : '—'}
        unit={h.hours_per_gram !== null ? 'h / g' : ''}
        label="hours of protection per gram"
        sub={h.hours_per_gram !== null ? `${fmt.n(8760 / h.hours_per_gram)} g for one year at this leakage` : 'not exhausted, so unbounded here'} />
    </div>
    </>
  )
}

function useClock(n, playing, speed) {
  const [hour, setHour] = useState(0)
  const raf = useRef(null); const last = useRef(0); const acc = useRef(0)
  useEffect(() => {
    if (!playing || !n) return
    const tick = (t) => {
      if (last.current) {
        acc.current += (t - last.current) * speed / 1000    // hours per second
        const step = Math.floor(acc.current)
        if (step > 0) { acc.current -= step; setHour((h) => (h + step) % n) }
      }
      last.current = t
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(raf.current); last.current = 0 }
  }, [playing, speed, n])
  return [hour, setHour]
}

function Animation({ y1, inputs, headline }) {
  const n = y1.loading_pct.length
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(48)          // hours of simulation per real second
  const [hour, setHour] = useClock(n, playing, speed)
  const frame = useMemo(() => Object.fromEntries(Object.keys(y1).map((k) => [k, y1[k][hour]])), [y1, hour])

  // A rolling 10-day window of the hourly trace, kept small so it redraws fast.
  const win = 240
  const start = Math.max(0, hour - win + 12)
  const data = useMemo(() => {
    const out = []
    for (let i = start; i < Math.min(n, start + win); i++) {
      out.push({ h: i, pane: y1.t_cold_f[i], dew: y1.dew_cav_f[i], rh: y1.rh_cav_pct[i], load: y1.loading_pct[i], film: y1.film_um[i] })
    }
    return out
  }, [y1, start, n])

  return (
    <div className="card">
      <h2>Play the first year</h2>
      <p className="lede">Air streams follow the hour's pressure and the loops, beads darken as the sieve fills, and an amber film climbs the existing pane when the cavity dew point beats its temperature.</p>
      <div className="anim">
        <div>
          <div className="stage"><Cavity frame={frame} inputs={inputs} /></div>
          <div className="controls">
            <button className="btn small" onClick={() => setPlaying((p) => !p)}>{playing ? 'Pause' : 'Play'}</button>
            <input type="range" min="0" max={n - 1} value={hour} onChange={(e) => { setPlaying(false); setHour(Number(e.target.value)) }} aria-label="Hour of year" />
            <span className="clock">{fmt.clock(hour)}</span>
          </div>
          <div className="controls">
            <span className="hint">Speed</span>
            <div className="speed">{[12, 48, 168, 720].map((s) => <button key={s} className="btn small" aria-pressed={speed === s} onClick={() => setSpeed(s)} style={speed === s ? { borderColor: C.glass, color: C.glass } : {}}>{s === 12 ? '½ day/s' : s === 48 ? '2 days/s' : s === 168 ? 'week/s' : 'month/s'}</button>)}</div>
          </div>
          <div className="readout">
            <Row label="pane" color={C.cold} tip="out_pane" value={`${frame.t_cold_f?.toFixed(1)} °F`} />
            <Row label="cavity dew point" color={C.water} tip="out_dew" value={`${frame.dew_cav_f?.toFixed(1)} °F`} />
            <Row label="cavity RH" tip="out_rh" value={`${frame.rh_cav_pct?.toFixed(1)} %`} />
            <Row label="supply air" tip="out_supply" value={`${frame.w_supply_gkg?.toFixed(2)} g/kg`} />
            <Row label="sieve loading" color={C.sand} tip="out_loading" value={`${frame.loading_pct?.toFixed(1)} %`} />
            <Row label="sieve holds air at" tip="out_rheq" value={`${frame.rh_eq_pct?.toFixed(2)} % RH`} />
            <Row label="taken up this hour" tip="out_uptake" value={`${(frame.uptake_g * 1000)?.toFixed(1)} mg`} />
            <Row label="film on pane" color={C.fog} tip="out_film" value={`${frame.film_um?.toFixed(2)} µm`} />
            <Row label="vent warming" tip="out_vent" value={`${frame.vent_rise_f?.toFixed(2)} °F`} />
            <Row label="outdoor air in now" tip="out_achout" value={`${frame.ach_out?.toFixed(3)} ACH`} />
            <Row label="room air in now" tip="out_achin" value={`${((frame.ach_total ?? 0) - (frame.ach_out ?? 0)).toFixed(3)} ACH`} />
            <Row label="pressure, room minus outdoors" tip="out_dp" value={frame.dp_pa !== undefined ? `${frame.dp_pa.toFixed(1)} Pa` : '—'} />
          </div>
        </div>
        <div>
          <ResponsiveContainer width="100%" height={230}>
            <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#e8edf2" vertical={false} />
              <XAxis dataKey="h" tickFormatter={(h) => fmt.clock(h).split(',')[0]} minTickGap={40} fontSize={11} />
              <YAxis yAxisId="t" fontSize={11} width={38} unit="°" />
              <Tooltip labelFormatter={(h) => fmt.clock(h)} formatter={(v, k) => [typeof v === 'number' ? v.toFixed(1) : v, k]} />
              <Legend iconType="plainline" />
              <Line yAxisId="t" dataKey="pane" name="pane °F" stroke={C.cold} dot={false} strokeWidth={2} isAnimationActive={false} />
              <Line yAxisId="t" dataKey="dew" name="cavity dew point °F" stroke={C.water} dot={false} strokeWidth={2} isAnimationActive={false} />
              <ReferenceLine yAxisId="t" x={hour} stroke="#16233a" strokeDasharray="3 3" />
            </ComposedChart>
          </ResponsiveContainer>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }} syncId="anim">
              <CartesianGrid stroke="#e8edf2" vertical={false} />
              <XAxis dataKey="h" tickFormatter={(h) => fmt.clock(h).split(',')[0]} minTickGap={40} fontSize={11} />
              <YAxis yAxisId="pct" fontSize={11} width={38} domain={[0, 100]} unit="%" />
              <YAxis yAxisId="um" orientation="right" fontSize={11} width={38} unit="µm" />
              <Tooltip labelFormatter={(h) => fmt.clock(h)} formatter={(v, k) => [typeof v === 'number' ? v.toFixed(2) : v, k]} />
              <Legend iconType="plainline" />
              <Area yAxisId="pct" dataKey="load" name="sieve loading %" stroke={C.sand} fill="#f3e8d2" isAnimationActive={false} />
              <Line yAxisId="pct" dataKey="rh" name="cavity RH %" stroke={C.water} dot={false} strokeDasharray="4 3" isAnimationActive={false} />
              <Line yAxisId="um" dataKey="film" name="film µm" stroke={C.fog} dot={false} strokeWidth={2} isAnimationActive={false} />
              <ReferenceLine yAxisId="pct" x={hour} stroke="#16233a" strokeDasharray="3 3" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

function LongChart({ daily, headline }) {
  const data = daily.loading.map((q, i) => ({
    d: i + 1, load: +(100 * q / 0.21).toFixed(2), rh: daily.rh_eq_pct[i], dew: daily.cavity_dew_f[i], pane: daily.pane_min_f[i], film: daily.film_um[i],
  }))
  const exDay = headline.exhausted_hour !== null ? headline.exhausted_hour / 24 : null
  const fcDay = headline.first_visible_hour !== null ? headline.first_visible_hour / 24 : null
  return (
    <div className="card">
      <h2>The whole run, day by day</h2>
      <p className="lede">Loading climbs until the sieve is full; the RH it can hold the cavity at rises with it. Once the cavity dew point crosses the nightly pane minimum, film appears.</p>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#e8edf2" vertical={false} />
          <XAxis dataKey="d" fontSize={11} tickFormatter={(d) => (d - 1) % 365 === 0 && d > 1 ? `year ${Math.floor((d - 1) / 365) + 1}` : fmt.clock(((d - 1) % 365) * 24).split(',')[0]} minTickGap={36} />
          <YAxis yAxisId="pct" fontSize={11} width={38} domain={[0, 100]} unit="%" />
          <YAxis yAxisId="t" orientation="right" fontSize={11} width={38} unit="°" />
          <Tooltip labelFormatter={(d) => `day ${d}`} />
          <Legend iconType="plainline" />
          <Area yAxisId="pct" dataKey="load" name="sieve loading %" stroke={C.sand} fill="#f3e8d2" isAnimationActive={false} />
          <Line yAxisId="pct" dataKey="rh" name="sieve holds air at % RH" stroke={C.sand} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Line yAxisId="t" dataKey="dew" name="cavity dew point °F" stroke={C.water} dot={false} isAnimationActive={false} />
          <Line yAxisId="t" dataKey="pane" name="pane nightly min °F" stroke={C.cold} dot={false} isAnimationActive={false} />
          {exDay !== null && <ReferenceLine yAxisId="pct" x={Math.round(exDay)} stroke={C.sand} label={{ value: 'full', position: 'top', fontSize: 11, fill: C.sand }} />}
          {fcDay !== null && <ReferenceLine yAxisId="pct" x={Math.round(fcDay)} stroke={C.fog} label={{ value: 'first fog', position: 'insideTopRight', fontSize: 11, fill: C.fog }} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function Years({ years }) {
  return (
    <div className="card">
      <h2>Per simulated year</h2>
      <table className="table">
        <thead><tr><th>Year</th><th>Water into sieve, g</th><th>Loading at year end</th><th>Sieve RH at year end</th><th>Condensed, g/m²</th><th>Hours condensing</th><th>Hours visible</th><th>Net from room / outdoor / bead, g</th><th>Oct–Mar outdoor net, g</th></tr></thead>
        <tbody>
          {years.map((y) => (
            <tr key={y.year}>
              <td>{y.year}</td><td>{fmt.n(y.water_into_desiccant_g, 2)}</td><td>{fmt.n(100 * y.loading_end / 0.21, 1)} %</td>
              <td>{fmt.n(100 * y.rh_eq_end, 2)} %</td><td>{fmt.n(1000 * y.condensed_kg_per_m2, 1)}</td><td>{fmt.n(y.hours_condensing)}</td><td>{fmt.n(y.hours_visible)}</td>
              <td>{fmt.n(y.net_room_g, 0)} / {fmt.n(y.net_outdoor_g, 0)} / {fmt.n(y.net_diffusion_g, 1)}</td>
              <td className={y.heating_outdoor_g < 0 ? 'neg' : ''}>{fmt.n(y.heating_outdoor_g, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Simulate({ result, busy }) {
  const [unit, setUnit] = useState('months')
  if (!result) return <div className="status">{busy ? 'Fetching weather and running the first year…' : 'Set inputs and run.'}</div>
  const { headline, inputs, year1, daily, years, contributions } = result
  return (
    <>
      {busy && <div className="status">Running…</div>}
      <Headline h={headline} inputs={inputs} unit={unit} setUnit={setUnit} />
      <SourceCard contributions={contributions} headline={headline} inputs={inputs} />
      {year1 && <Animation y1={year1} inputs={inputs} headline={headline} />}
      <LongChart daily={daily} headline={headline} />
      <Years years={years} />
    </>
  )
}
