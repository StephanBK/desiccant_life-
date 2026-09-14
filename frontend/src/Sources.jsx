import { fmt } from './api.js'
import { Tip } from './Tip.jsx'

// Where the water came from: net contribution of the three sources over the
// sieve's life. Signed: a negative source carried water OUT (its air was
// drier than the cavity). The bar shows the positive sources in proportion;
// removals are listed beside it so the reader sees them without the bar
// having to draw a negative width.
export const SRC = [
  { k: 'room', label: 'Room air', color: '#1f9e9a' },
  { k: 'outdoor', label: 'Outdoor air', color: '#6e8fb5' },
  { k: 'diffusion', label: 'Sealant diffusion', color: '#9a7330' },
]

export function pctText(c, k) {
  const p = c[`${k}_pct`]
  return p === null || p === undefined ? '' : `${fmt.n(p, Math.abs(p) < 10 ? 1 : 0)} %`
}

export function SourceBar({ c, height = 14 }) {
  const pos = SRC.filter((s) => c[`${s.k}_g`] > 0)
  const sum = pos.reduce((a, s) => a + c[`${s.k}_g`], 0)
  if (sum <= 0) return <div className="srcbar empty">no source is adding water; see the grams</div>
  return (
    <div className="srcbar" style={{ height }} role="img" aria-label="Share of net water by source">
      {pos.map((s) => <i key={s.k} style={{ width: `${100 * c[`${s.k}_g`] / sum}%`, background: s.color }} />)}
    </div>
  )
}

export function SourceLegend({ c, compact }) {
  return (
    <div className={`srclegend${compact ? ' compact' : ''}`}>
      {SRC.map((s) => {
        const g = c[`${s.k}_g`]
        const removed = g < 0
        return (
          <span key={s.k} className={removed ? 'removed' : ''}>
            <i className="dot" style={{ background: s.color }} />
            {s.label}: <b>{removed ? `removed ${fmt.n(-g, Math.abs(g) < 10 ? 2 : 1)} g` : `${fmt.n(g, Math.abs(g) < 10 ? 2 : 1)} g`}</b>
            {c[`${s.k}_pct`] !== null && <em> ({pctText(c, s.k)})</em>}
          </span>
        )
      })}
    </div>
  )
}

export function SourceCard({ contributions, headline }) {
  if (!contributions) return null
  const c = contributions.life
  const hrs = contributions.life_hours
  const lifeTitle = headline.exhausted_hour !== null
    ? `over the sieve's life, ${fmt.n(hrs)} hours`
    : `over the ${fmt.n(hrs / 8760, 1)}-year run (never full)`
  return (
    <div className="card source">
      <div className="source-head">
        <h2>Where the water came from<Tip id="out_source" inline /></h2>
        <span className="hint">{lifeTitle}</span>
      </div>
      <SourceBar c={c} />
      <SourceLegend c={c} />
      <p className="hint">Net water each path delivered to the cavity. A path reads as a removal when its air was drier than the cavity air, which is what cold outdoor air is in winter. Shares are of the net total and sum to 100 %.</p>
    </div>
  )
}
