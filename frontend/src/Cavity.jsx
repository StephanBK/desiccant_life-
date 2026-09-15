// Cavity cross-section, plan view: outdoors on the left, existing pane,
// the cavity with the desiccant cartridge at the bottom, the retrofit IGU,
// room on the right. Everything that moves is driven by one hour of the
// year-1 trace: stream widths by ACH, bead colour by loading, film height
// by microns on the pane, and a haze in the cavity by RH.

const W = 300, H = 420

function Stream({ x, y1, y2, dir, strength, color, label }) {
  // Arrow arrays whose count and length scale with ACH (log scale so the
  // hermetic ladder still shows something).
  const n = Math.max(1, Math.min(7, Math.round(1 + Math.log10(1 + strength * 10) * 2.2)))
  const len = 14 + Math.min(26, Math.log10(1 + strength) * 22)
  const ys = Array.from({ length: n }, (_, i) => y1 + ((y2 - y1) * (i + 1)) / (n + 1))
  return (
    <g stroke={color} strokeWidth="2" fill={color} opacity="0.9">
      {ys.map((y) => (
        <g key={y}>
          <line x1={x} y1={y} x2={x + dir * len} y2={y} />
          <polygon points={`${x + dir * len},${y - 3} ${x + dir * len},${y + 3} ${x + dir * (len + 6)},${y}`} />
        </g>
      ))}
      <text x={x + dir * (len / 2)} y={y2 + 14} textAnchor="middle" fontSize="10" stroke="none" fill={color} fontWeight="700">{label}</text>
    </g>
  )
}

export default function Cavity({ frame, inputs }) {
  const f = frame || {}
  const paneX = 96, paneW = 8, cavX = paneX + paneW, cavW = 92, iguX = cavX + cavW, iguW = 14
  const top = 40, bot = 380
  const rh = Math.min(100, f.rh_cav_pct ?? 0)
  const film = Math.min(100, f.film_um ?? 0)
  const load = Math.min(100, f.loading_pct ?? 0)
  const tCold = f.t_cold_f
  const haze = Math.min(0.6, rh / 100 * 0.6)
  const filmH = (bot - top) * Math.min(1, film / 100)
  const coldTint = tCold === undefined ? '#6e8fb5' : tCold < 32 ? '#5a7fb0' : tCold < 45 ? '#7f9dc4' : '#a9bcd6'

  // Desiccant cartridge: a bed of beads at the bottom of the cavity; each
  // bead's colour interpolates sand -> dark umber with loading.
  const beadRows = 4, beadCols = 7, br = 4.8
  const bedTop = bot - 62, bedX = cavX + 8
  const beadColor = (i) => {
    // fill bottom-up so a half-full cartridge reads as half dark
    const rank = i / (beadRows * beadCols)
    const dark = load / 100 > rank ? 1 : 0
    return dark ? '#6b4b1f' : '#e2c98f'
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Cavity cross-section animation">
      {/* outdoors / room fields */}
      <rect x="0" y="0" width={paneX} height={H} fill="#e6edf5" />
      <rect x={iguX + iguW} y="0" width={W - iguX - iguW} height={H} fill="#f4f1ea" />
      <text x={paneX / 2} y="22" textAnchor="middle" fontSize="11" fill="#4b5a72" fontWeight="700">outdoors</text>
      <text x={paneX / 2} y="36" textAnchor="middle" fontSize="11" fill="#4b5a72">{f.t_out_f !== undefined ? `${f.t_out_f.toFixed(0)} °F` : ''}</text>
      <text x={(iguX + iguW + W) / 2} y="22" textAnchor="middle" fontSize="11" fill="#4b5a72" fontWeight="700">room</text>
      <text x={(iguX + iguW + W) / 2} y="36" textAnchor="middle" fontSize="11" fill="#4b5a72">{inputs ? `${inputs.t_in_f} °F · ${inputs.rh_in_pct}% RH` : ''}</text>

      {/* cavity air with RH haze */}
      <rect x={cavX} y={top} width={cavW} height={bot - top} fill="#ffffff" />
      <rect x={cavX} y={top} width={cavW} height={bot - top} fill="#1f9e9a" opacity={haze} />
      <text x={cavX + cavW / 2} y={top + 16} textAnchor="middle" fontSize="11" fill="#16233a" fontWeight="700">cavity</text>
      <text x={cavX + cavW / 2} y={top + 30} textAnchor="middle" fontSize="11" fill="#16233a">{f.rh_cav_pct !== undefined ? `${f.rh_cav_pct.toFixed(1)}% RH` : ''}</text>

      {/* existing pane, cold, with film growing from the bottom on its cavity face */}
      <rect x={paneX} y={top} width={paneW} height={bot - top} fill={coldTint} />
      <rect x={cavX} y={bot - filmH} width={3} height={filmH} fill="#d0642f" opacity="0.9" />
      {film > 5 && <rect x={cavX} y={bot - filmH} width={cavW * 0.35} height={filmH} fill="url(#fog)" opacity="0.55" />}
      <text x={paneX + paneW / 2} y={bot + 16} textAnchor="middle" fontSize="10" fill="#4b5a72">existing</text>
      <text x={paneX + paneW / 2} y={bot + 28} textAnchor="middle" fontSize="10" fill="#4b5a72">{tCold !== undefined ? `${tCold.toFixed(0)} °F` : ''}</text>

      {/* retrofit IGU */}
      <rect x={iguX} y={top} width={iguW} height={bot - top} fill="#c9d8ea" />
      <rect x={iguX + 5} y={top} width={4} height={bot - top} fill="#eef3f9" />
      <text x={iguX + iguW / 2} y={bot + 16} textAnchor="middle" fontSize="10" fill="#4b5a72">retrofit</text>
      <text x={iguX + iguW / 2} y={bot + 28} textAnchor="middle" fontSize="10" fill="#4b5a72">IGU</text>

      {/* streams */}
      <Stream x={paneX - 4} y1={top + 40} y2={top + 130} dir={1} strength={f.ach_out ?? 0} color="#1f5fa8" label={f.ach_out !== undefined ? `${f.ach_out.toFixed(2)} ACH` : ''} />
      <Stream x={iguX + iguW + 4} y1={top + 40} y2={top + 130} dir={-1} strength={f.ach_total !== undefined ? Math.max(0, f.ach_total - (f.ach_out ?? 0)) : (inputs?.ach_in ?? 0)} color="#1f9e9a" label={f.ach_total !== undefined ? `${Math.max(0, f.ach_total - (f.ach_out ?? 0)).toFixed(2)} ACH` : (inputs ? `${Number(inputs.ach_in).toFixed(2)} ACH` : '')} />

      {/* desiccant bed */}
      <rect x={bedX - 4} y={bedTop - 4} width={beadCols * 11 + 8} height={beadRows * 11 + 8} rx="4" fill="#ffffff" stroke="#c99c55" strokeWidth="1.5" />
      {Array.from({ length: beadRows * beadCols }, (_, i) => {
        const r = beadRows - 1 - Math.floor(i / beadCols), c = i % beadCols
        return <circle key={i} cx={bedX + c * 11 + 5.5} cy={bedTop + r * 11 + 5.5} r={br} fill={beadColor(i)} />
      })}
      <text x={bedX + (beadCols * 11) / 2} y={bedTop - 10} textAnchor="middle" fontSize="10" fill="#9a7330" fontWeight="700">{`desiccant ${load.toFixed(0)}%`}</text>

      <defs>
        <linearGradient id="fog" x1="0" x2="1">
          <stop offset="0" stopColor="#d0642f" stopOpacity="0.8" />
          <stop offset="1" stopColor="#d0642f" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  )
}
