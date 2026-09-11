import { useEffect, useState } from 'react'
import { api, DEFAULT_INPUTS } from './api.js'
import Rail from './Rail.jsx'
import Simulate from './Simulate.jsx'
import Sweep from './Sweep.jsx'
import Explain from './Explain.jsx'

const TABS = [['simulate', 'Simulate'], ['sweep', 'Sweep'], ['explain', 'Explain']]

export default function App() {
  const [tab, setTab] = useState('simulate')
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
        <div className="brand"><span className="mark" />Desiccant Lifetime<small>INOVUES</small></div>
        <nav className="tabs" role="tablist">
          {TABS.map(([k, label]) => (
            <button key={k} role="tab" className="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>
          ))}
        </nav>
        <span className="spacer" />
        {result && <a className="btn" href={api.exportUrl(inp)}>Download Excel</a>}
      </header>
      <div className="main">
        <Rail inp={inp} set={set} presets={presets} busy={busy} onRun={() => run()} />
        <main className="content">
          {error && <div className="status err">{error}</div>}
          {tab === 'simulate' && <Simulate result={result} busy={busy} inp={inp} />}
          {tab === 'sweep' && <Sweep inp={inp} presets={presets} />}
          {tab === 'explain' && <Explain result={result} presets={presets} inp={inp} />}
        </main>
      </div>
    </div>
  )
}
