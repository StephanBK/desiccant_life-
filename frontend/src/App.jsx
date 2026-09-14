import { useEffect, useState } from 'react'
import { api, DEFAULT_INPUTS } from './api.js'
import Rail from './Rail.jsx'
import Simulate from './Simulate.jsx'
import Sweep from './Sweep.jsx'
import Explain from './Explain.jsx'
import Cinema from './Cinema.jsx'

const srcPct = (c, k) => {
  const p = c[`${k}_pct`]
  if (p === null || p === undefined) return `${Math.round(c[`${k}_g`])} g`
  return `${Math.round(p)} %`
}
const alNum = (v, presets) => (typeof v === 'number' ? v : (presets?.find((p) => p.key === v)?.al_cfm_ft2 ?? v))

const TABS = [['simulate', 'Simulate'], ['cinema', 'Watch'], ['sweep', 'Sweep'], ['explain', 'Explain']]

export default function App() {
  const [tab, setTab] = useState('simulate')
  const [railOpen, setRailOpen] = useState(false)
  const [inp, setInp] = useState(DEFAULT_INPUTS)
  const [presets, setPresets] = useState(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { api.presets().then(setPresets).catch((e) => setError(e.message)) }, [])

  async function run(next = inp) {
    setBusy(true); setError(null)
    try { setResult(await api.lifetime(next)) }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  useEffect(() => { run(DEFAULT_INPUTS) }, [])   // first load

  const set = (k, v) => setInp((s) => ({ ...s, [k]: v }))

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><img className="mark" src="/inovues-mark.png" alt="INOVUES" /><img className="word" src="/inovues-wordmark.png" alt="" /><small>Desiccant Lifetime</small></div>
        <nav className="tabs" role="tablist">
          {TABS.map(([k, label]) => (
            <button key={k} role="tab" className="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>
          ))}
        </nav>
        <span className="spacer" />
        <button className="btn" aria-pressed={railOpen} onClick={() => setRailOpen((o) => !o)}>{railOpen ? 'Hide inputs' : 'Inputs'}</button>
        {result && <a className="btn" href={api.exportUrl(inp)}>Download Excel</a>}
      </header>
      <div className={`main${railOpen ? ' rail-open' : ''}`}>
        {railOpen && <Rail inp={inp} set={set} presets={presets} busy={busy} onRun={() => run()} onClose={() => setRailOpen(false)} />}
        <main className="content">
          {!railOpen && (
            <div className="summary">
              <span>{inp.address}</span><span>{inp.width_in} × {inp.height_in} × {inp.offset_in} in</span>
              <span>existing {alNum(inp.al_out, presets?.al_out)} · retrofit {alNum(inp.al_in, presets?.al_in)} cfm/ft²</span><span>{inp.t_in} °F / {inp.rh_in} % RH</span>
              <span>{inp.grams} g {inp.desiccant === 'ms3a' ? '3A' : inp.desiccant}</span>
              {result?.contributions && <span className="srcsum">water from room {srcPct(result.contributions.life, 'room')} · outdoor {srcPct(result.contributions.life, 'outdoor')}</span>}
              <button className="btn small primary" onClick={() => setRailOpen(true)}>Edit inputs</button>
            </div>
          )}
          {error && <div className="status err">{error}</div>}
          {tab === 'simulate' && <Simulate result={result} busy={busy} inp={inp} />}
          {tab === 'cinema' && <Cinema result={result} active={tab === 'cinema'} />}
          {tab === 'sweep' && <Sweep inp={inp} presets={presets} />}
          {tab === 'explain' && <Explain result={result} presets={presets} inp={inp} />}
        </main>
      </div>
    </div>
  )
}
