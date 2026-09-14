import { fmt } from './api.js'
import { Tip } from './Tip.jsx'

// Where the water came from: net contribution of the three sources over the
// window (the sieve's life, or the whole run when it never fills). Signed: a
// negative source carried water OUT because its air was drier than the
// cavity. Shares are only shown when every path is a source; otherwise the
// grams carry the story, as adds and removes on a common scale, and the
// numbers are shown PER YEAR when the window is longer than a year.
export const SRC = [
  { k: 'room', label: 'Room air', color: '#1f9e9a' },
  { k: 'outdoor', label: 'Outdoor air', color: '#6e8fb5' },
  { k: 'diffusion', label: 'Sealant bead', color: '#9a7330' },
]

const g1 = (x) => fmt.n(x, Math.abs(x) < 10 ? 2 : Math.abs(x) < 100 ? 1 : 0)

export function scaleWindow(c, hours) {
  const years = hours / 8760
  const per = years > 1.05 ? years : 1
  const out = {}
  for (const s of SRC) { out[`${s.k}_g`] = c[`${s.k}_g`] / per; out[`${s.k}_pct`] = c[`${s.k}_pct`] }
  out.total_g = c.total_g / per
  out.perYear = per > 1
  out.years = years
  return out
}

export function hasShares(c) { return SRC.every((s) => c[`${s.k}_pct`] !== null && c[`${s.k}_pct`] !== undefined) }

export function SourceBar({ c, height = 14 }) {
  if (hasShares(c)) {
    const sum = SRC.reduce((a, s) => a + Math.max(0, c[`${s.k}_g`]), 0)
    return (
      <div className="srcbar" style={{ height }} role="img" aria-label="Share of water by source">
        {SRC.map((s) => <i key={s.k} style={{ width: `${100 * Math.max(0, c[`${s.k}_g`]) / sum}%`, background: s.color }} />)}
      </div>
    )
  }
  // Mixed signs: adds and removes on one scale, zero in the middle.
  const big = Math.max(...SRC.map((s) => Math.abs(c[`${s.k}_g`])), 1e-9)
  return (
    <div className="srcbars" role="img" aria-label="Water added and removed by each path">
      {SRC.map((s) => {
        const g = c[`${s.k}_g`]; const w = 50 * Math.abs(g) / big
        return (
          <div key={s.k} className="srcrow">
            <span className="srclabel"><i className="dot" style={{ background: s.color }} />{s.label}</span>
            <div className="srctrack"><i style={{ background: s.color, width: `${w}%`, [g < 0 ? 'right' : 'left']: '50%' }} /></div>
            <b className={g < 0 ? 'neg' : ''}>{g < 0 ? '−' : '+'}{g1(Math.abs(g))} g</b>
          </div>
        )
      })}
      <div className="srcaxis"><span>removes</span><span>adds</span></div>
    </div>
  )
}

export function SourceLegend({ c, compact }) {
  if (!hasShares(c)) return null
  return (
    <div className={`srclegend${compact ? ' compact' : ''}`}>
      {SRC.map((s) => (
        <span key={s.k}><i className="dot" style={{ background: s.color }} />{s.label}: <b>{g1(c[`${s.k}_g`])} g</b><em> ({fmt.n(c[`${s.k}_pct`], Math.abs(c[`${s.k}_pct`]) < 10 ? 1 : 0)} %)</em></span>
      ))}
    </div>
  )
}

// The run-off sentence rests on two estimates from the pane model (film
// cap 100 um, instant evaporation), so it is returned with a flag and the
// card tags it.
export function readingLine(c, grams, exhausted) {
  const unit = c.perYear ? ' g per year' : ' g'
  if (hasShares(c)) return `All three paths were sources: the cavity air next to a fresh sieve is drier than anything outside it. Together they delivered ${g1(c.total_g)}${unit}, which is what the sieve took.`
  const parts = SRC.map((s) => { const g = c[`${s.k}_g`]; return `${s.label.toLowerCase()} ${g < 0 ? 'removed' : 'added'} ${g1(Math.abs(g))}${unit}` }).join(', ')
  const net = c.total_g
  let tail
  if (Math.abs(net) < 0.02 * Math.max(...SRC.map((s) => Math.abs(c[`${s.k}_g`])), 1e-9)) tail = 'Net about zero: what came in went back out; the pane only held water briefly.'
  else if (net > 0) tail = grams > 0 && exhausted ? `Net ${g1(net)}${unit} stayed in the cavity: the sieve took it until full, and what condensed after that ran off the pane.` : `Net ${g1(net)}${unit} stayed in the cavity, which with no sieve means it condensed on the pane and ran off.`
  else tail = `Net ${g1(-net)}${unit} left the cavity: it started wetter than the air around it.`
  return `${parts.charAt(0).toUpperCase()}${parts.slice(1)}. ${tail}`
}

export function runoffIsEstimate(c) {
  const big = Math.max(...SRC.map((s) => Math.abs(c[`${s.k}_g`])), 1e-9)
  return !hasShares(c) && c.total_g > 0.02 * big
}

export function SourceCard({ contributions, headline, inputs }) {
  if (!contributions) return null
  const c = scaleWindow(contributions.life, contributions.life_hours)
  const exhausted = headline.exhausted_hour !== null
  const title = exhausted
    ? `over the sieve's life, ${fmt.n(contributions.life_hours)} hours`
    : `${c.perYear ? 'per year, averaged over' : 'over'} the ${fmt.n(c.years, c.years < 10 ? 1 : 0)}-year run${inputs?.grams > 0 ? ' (never full)' : ' (no desiccant)'}`
  return (
    <div className="card source">
      <div className="source-head">
        <h2>{inputs?.grams > 0 ? 'Where the water came from' : 'Water in and out of the cavity'}<Tip id="out_source" inline /></h2>
        <span className="hint">{title}</span>
      </div>
      <SourceBar c={c} />
      <SourceLegend c={c} />
      <p className="hint">{readingLine(c, inputs?.grams ?? 0, exhausted)}{runoffIsEstimate(c) && <> <span className="est">estimate</span> run-off depends on the 100 µm film cap and instant morning evaporation, both unmeasured.</>} A path removes water when its air is drier than the cavity air: cold outdoor air in winter, room air in a humid summer.</p>
    </div>
  )
}
