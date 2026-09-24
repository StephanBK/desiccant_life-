import { useEffect, useMemo, useRef, useState } from 'react'
import { fmt } from './api.js'

// Cinematic view. One idea on screen: the desiccant vessel filling, day by
// day, over the whole run. Everything else is a cue: the date, the outdoor
// weather, the pane's cold, and the two moments that matter (full, first
// fog). Dark stage so the beads and the amber read like light.

const COLS = 17, ROWS = 15, R = 9.2, DX = 21, DY = 18.5
const VX = 60, VY = 40, VW = COLS * DX + 12, VH = ROWS * DY + 22

function seeded(n) {           // small deterministic jitter, same every render
  let s = 7
  return Array.from({ length: n }, () => { s = (s * 9301 + 49297) % 233280; return s / 233280 })
}

function useBeads() {
  return useMemo(() => {
    const jit = seeded(COLS * ROWS)
    const beads = []
    for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) {
      const i = r * COLS + c
      const x = VX + 14 + c * DX + (r % 2 ? DX / 2 : 0)
      if (x > VX + VW - 14) continue
      const y = VY + VH - 14 - r * DY
      // fill threshold rises with row, with jitter so the front is organic
      const thr = Math.min(1, Math.max(0, (r + 0.5 * jit[i] - 0.25) / ROWS))
      beads.push({ x, y, thr, k: i })
    }
    return beads
  }, [])
}

const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t))
const SAND = [226, 201, 143], DEEP = [92, 58, 22]
const beadFill = (load, thr) => {
  const t = Math.min(1, Math.max(0, (load - thr) * 6 + 0.5))     // soft front
  const c = mix(SAND, DEEP, t)
  return `rgb(${c.join(',')})`
}

function useDayClock(n, playing, daysPerSec) {
  const [day, setDay] = useState(0)
  const raf = useRef(null); const last = useRef(0); const acc = useRef(0)
  useEffect(() => {
    if (!playing || !n) return
    const tick = (t) => {
      if (last.current) {
        acc.current += (t - last.current) * daysPerSec / 1000
        const step = Math.floor(acc.current)
        if (step > 0) { acc.current -= step; setDay((d) => (d + step >= n ? 0 : d + step)) }
      }
      last.current = t
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(raf.current); last.current = 0 }
  }, [playing, daysPerSec, n])
  return [day, setDay]
}

const dayLabel = (d) => {
  const y = Math.floor(d / 365) + 1
  const date = new Date(Date.UTC(2021, 0, 1 + (d % 365)))
  return { year: y, date: `${date.toLocaleString('en-US', { month: 'long', timeZone: 'UTC' })} ${date.getUTCDate()}` }
}

export default function Cinema({ result, active }) {
  const beads = useBeads()
  const stage = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(20)
  const [showHelp, setShowHelp] = useState(true)
  const daily = result?.daily
  const n = daily?.loading?.length || 0
  const [day, setDay] = useDayClock(n, playing, speed)

  useEffect(() => { if (active && n) { setDay(0); setPlaying(true) } else setPlaying(false) }, [active, n])
  useEffect(() => { if (!playing) return; const t = setTimeout(() => setShowHelp(false), 4000); return () => clearTimeout(t) }, [playing])

  if (!result) return <div className="status">Run a simulation first.</div>

  const h = result.headline, inp = result.inputs, qmax = result.q_max_25 || 0.21
  const load = Math.min(1, (daily.loading[day] || 0) / qmax)
  const fullDay = h.exhausted_hour !== null ? Math.floor(h.exhausted_hour / 24) : null
  const fogDay = h.first_visible_hour !== null ? Math.floor(h.first_visible_hour / 24) : null   // visible film, as in the 277 app
  const isFull = fullDay !== null && day >= fullDay
  const fogNow = fogDay !== null && day >= fogDay && day < fogDay + 3
  const fogged = fogDay !== null && day >= fogDay
  const { year, date } = dayLabel(day)
  const tOut = daily.t_out_f?.[day], rhOut = daily.rh_out_pct?.[day], paneMin = daily.pane_min_f?.[day], dew = daily.cavity_dew_f?.[day], film = daily.film_um?.[day] || 0
  const rhEq = daily.rh_eq_pct?.[day] || 0
  const cold = paneMin !== undefined ? Math.min(1, Math.max(0, (50 - paneMin) / 60)) : 0
  const pct = Math.round(load * 100)
  const ring = 2 * Math.PI * 92

  const full = () => { const el = stage.current; if (!el) return; if (document.fullscreenElement) document.exitFullscreen(); else el.requestFullscreen?.() }

  return (
    <div className="cinema" ref={stage}>
      <div className="cin-top">
        <div className="cin-brand"><img className="mark" src="/inovues-mark.png" alt="INOVUES" /><div><img className="word" src="/inovues-wordmark.png" alt="" /><span>Desiccant lifetime</span></div></div>
        <div className="cin-date"><span className="cin-year">Year {year}</span><span>{date}</span></div>
        <div className="cin-actions">
          <button className="cin-btn" onClick={() => setPlaying((p) => !p)}>{playing ? 'Pause' : 'Play'}</button>
          {[5, 20, 60].map((s) => <button key={s} className="cin-btn" aria-pressed={speed === s} onClick={() => setSpeed(s)}>{s === 5 ? '½ wk/s' : s === 20 ? '3 wk/s' : '2 mo/s'}</button>)}
          <button className="cin-btn" onClick={full}>Fullscreen</button>
        </div>
      </div>

      <div className="cin-stage">
        {/* left: outdoors and the cold pane */}
        <div className="cin-side">
          <div className="cin-kv"><span>outdoors</span><b>{tOut !== undefined ? `${tOut.toFixed(0)} °F` : ''}</b><small>{rhOut !== undefined ? `${rhOut.toFixed(0)} % RH` : ''}</small></div>
          <div className="cin-pane" style={{ '--cold': cold, '--film': Math.min(1, film / 20) }}>
            <div className="cin-frost" style={{ opacity: fogged ? Math.min(1, film / 5) : 0 }} />
          </div>
          <div className="cin-kv"><span>existing pane, night low</span><b>{paneMin !== undefined ? `${paneMin.toFixed(0)} °F` : ''}</b><small>{dew !== undefined ? `cavity dew point ${dew.toFixed(0)} °F` : ''}</small></div>
        </div>

        {/* centre: the vessel */}
        <div className="cin-centre">
          <svg viewBox={`0 0 ${VW + 2 * VX} ${VH + 2 * VY + 20}`} className="cin-vessel" role="img" aria-label="Desiccant vessel filling">
            <defs>
              <linearGradient id="glass" x1="0" x2="1"><stop offset="0" stopColor="#fff" stopOpacity="0.16" /><stop offset="0.5" stopColor="#fff" stopOpacity="0.02" /><stop offset="1" stopColor="#fff" stopOpacity="0.12" /></linearGradient>
              <filter id="glow"><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
            </defs>
            <rect x={VX} y={VY} width={VW} height={VH} rx="18" fill="#0d1626" stroke="#3b4a63" strokeWidth="2" />
            {beads.map((b) => <circle key={b.k} cx={b.x} cy={b.y} r={R} fill={beadFill(load, b.thr)} />)}
            <rect x={VX} y={VY} width={VW} height={VH} rx="18" fill="url(#glass)" pointerEvents="none" />
            {/* incoming moisture: drifting motes whose count follows exchange rate */}
            {playing && !isFull && Array.from({ length: Math.min(14, Math.round(Math.log10(1 + (result?.pressure?.mean_ach ?? (inp.ach_out + inp.ach_in))) * 6)) }, (_, i) => (
              <circle key={`m${i}`} className="mote" style={{ animationDelay: `${(i * 0.37) % 2.6}s`, animationDuration: `${2.2 + (i % 4) * 0.4}s` }} cx={VX - 20} cy={VY + 30 + (i * 37) % (VH - 60)} r="2.2" filter="url(#glow)" />
            ))}
          </svg>
          <div className="cin-gauge">
            <svg viewBox="0 0 220 220" width="220" height="220">
              <circle cx="110" cy="110" r="92" fill="none" stroke="#243044" strokeWidth="10" />
              <circle cx="110" cy="110" r="92" fill="none" stroke={isFull ? '#d0642f' : '#c99c55'} strokeWidth="10" strokeLinecap="round" strokeDasharray={`${ring * load} ${ring}`} transform="rotate(-90 110 110)" />
            </svg>
            <div className="cin-pct"><b>{pct}<small>%</small></b><span>saturated</span></div>
          </div>
        </div>

        {/* right: the sieve's grip and the two milestones */}
        <div className="cin-side">
          <div className="cin-kv"><span>sieve holds cavity air at</span><b>{rhEq.toFixed(rhEq < 1 ? 2 : 0)} % RH</b><small>rises as it fills; protection fades before "full"</small></div>
          <div className={`cin-milestone${isFull ? ' hit' : ''}`}><span>full</span><b>{fullDay !== null ? `day ${fullDay + 1}` : `> ${h.years_run} yr`}</b><small>{h.exhausted_hour !== null ? `${fmt.n(h.exhausted_hour)} h · ${fmt.n(h.hours_per_gram, 2)} h per gram` : 'not within run'}</small></div>
          <div className={`cin-milestone fog${fogged ? ' hit' : ''}`}><span>first fog</span><b>{fogDay !== null ? `day ${fogDay + 1}` : 'none'}</b><small>{fogDay !== null ? dayLabel(fogDay).date + `, year ${dayLabel(fogDay).year}` : `no visible fog in ${h.years_run} yr`}</small></div>
          <div className="cin-kv"><span>{fmt.n(inp.grams)} g of {inp.desiccant === 'ms3a' ? '3A molecular sieve' : inp.desiccant}</span><b>{fmt.n(inp.capacity_g, 1)} g</b><small>water it can hold</small></div>
        </div>

        {fogNow && <div className="cin-flash"><b>First fog</b><span>{date}, year {year}. The cavity dew point beat the pane.</span></div>}
        {showHelp && !fogNow && <div className="cin-help">Drag the timeline or press Play. Fullscreen for the wall.</div>}
      </div>

      <div className="cin-bottom">
        <input type="range" min="0" max={Math.max(0, n - 1)} value={day} onChange={(e) => { setPlaying(false); setDay(Number(e.target.value)) }} aria-label="Day of run" />
        <div className="cin-marks">
          {fullDay !== null && <i style={{ left: `${100 * fullDay / Math.max(1, n - 1)}%`, background: '#c99c55' }} title="full" />}
          {fogDay !== null && <i style={{ left: `${100 * fogDay / Math.max(1, n - 1)}%`, background: '#d0642f' }} title="first fog" />}
          {Array.from({ length: Math.floor((n - 1) / 365) }, (_, i) => <em key={i} style={{ left: `${100 * (365 * (i + 1)) / Math.max(1, n - 1)}%` }} />)}
        </div>
        <div className="cin-foot"><span>{inp.address}</span><span>existing {inp.al_out} · retrofit {inp.al_in} cfm/ft² · {fmt.g(result?.pressure?.mean_ach ?? (inp.ach_out + inp.ach_in))} ACH mean exchange</span><span>{inp.t_in_f} °F / {inp.rh_in_pct} % RH room</span><span>day {day + 1} of {n}</span></div>
      </div>
    </div>
  )
}
