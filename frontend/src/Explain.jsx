import { fmt } from './api.js'
import { SourceBar, SourceLegend, scaleWindow } from './Sources.jsx'

const C = { glass: '#1f5fa8', water: '#1f9e9a', fog: '#d0642f', sand: '#9a7330', cold: '#6e8fb5', ink2: '#4b5a72', line: '#d5dce4' }

function Step({ title, children, figure }) {
  return (
    <section className="step">
      <div>
        <h3>{title}</h3>
        {children}
      </div>
      <div>{figure}</div>
    </section>
  )
}

function Live({ rows }) {
  return <div className="live">{rows.map(([k, v]) => [<span key={k + 'k'}>{k}</span>, <span key={k + 'v'}>{v}</span>])}</div>
}

/* ---- figures ---------------------------------------------------------- */

function FigInventory({ w, h, off }) {
  return (
    <svg viewBox="0 0 300 200">
      <rect x="40" y="30" width="180" height="120" fill="#fff" stroke={C.line} />
      <rect x="40" y="30" width="180" height="120" fill={C.water} opacity="0.12" />
      <line x1="40" y1="165" x2="220" y2="165" stroke={C.ink2} /><text x="130" y="180" textAnchor="middle" fontSize="11" fill={C.ink2}>width {w} in</text>
      <line x1="235" y1="30" x2="235" y2="150" stroke={C.ink2} /><text x="248" y="95" fontSize="11" fill={C.ink2}>height {h} in</text>
      <line x1="220" y1="30" x2="262" y2="12" stroke={C.ink2} /><text x="262" y="10" fontSize="11" fill={C.ink2}>offset {off} in</text>
      <text x="130" y="95" textAnchor="middle" fontSize="12" fill={C.water} fontWeight="700">cavity air, W_cav</text>
    </svg>
  )
}

function FigStreams({ aOut, aIn }) {
  return (
    <svg viewBox="0 0 300 200">
      <rect x="0" y="0" width="90" height="200" fill="#e6edf5" /><rect x="210" y="0" width="90" height="200" fill="#f4f1ea" />
      <rect x="90" y="0" width="8" height="200" fill={C.cold} /><rect x="202" y="0" width="8" height="200" fill="#c9d8ea" />
      <text x="45" y="20" textAnchor="middle" fontSize="11" fill={C.ink2}>outdoor W_out</text><text x="255" y="20" textAnchor="middle" fontSize="11" fill={C.ink2}>room W_room</text>
      <g stroke={C.glass} strokeWidth="2"><line x1="60" y1="80" x2="120" y2="80" /><polygon points="120,76 128,80 120,84" fill={C.glass} /></g>
      <text x="150" y="70" textAnchor="middle" fontSize="11" fill={C.glass} fontWeight="700">{aOut} ACH</text>
      <g stroke={C.water} strokeWidth="2"><line x1="240" y1="130" x2="180" y2="130" /><polygon points="180,126 172,130 180,134" fill={C.water} /></g>
      <text x="150" y="150" textAnchor="middle" fontSize="11" fill={C.water} fontWeight="700">{aIn} ACH</text>
      <text x="150" y="110" textAnchor="middle" fontSize="11" fill={C.ink2}>W_cav</text>
    </svg>
  )
}

function FigEnergy() {
  // Energy-flow cross-section: conduction chain outdoors -> pane -> cavity
  // -> IGU -> room, solar in, sky out, vent stream as a parallel path.
  return (
    <svg viewBox="0 0 300 220">
      <rect x="0" y="0" width="70" height="220" fill="#e6edf5" /><rect x="230" y="0" width="70" height="220" fill="#f4f1ea" />
      <rect x="70" y="20" width="8" height="180" fill={C.cold} /><rect x="215" y="20" width="15" height="180" fill="#c9d8ea" />
      <rect x="78" y="20" width="137" height="180" fill="#fff" />
      <text x="35" y="14" textAnchor="middle" fontSize="10" fill={C.ink2}>T_out</text><text x="265" y="14" textAnchor="middle" fontSize="10" fill={C.ink2}>T_room</text>
      {/* conduction chain */}
      <g stroke={C.ink2} strokeWidth="1.5" fill="none">
        <path d="M20 110 h40" /><path d="M78 110 h137" strokeDasharray="4 3" /><path d="M230 110 h40" />
      </g>
      <text x="40" y="104" textAnchor="middle" fontSize="9" fill={C.ink2}>G_out = U/f</text>
      <text x="146" y="104" textAnchor="middle" fontSize="9" fill={C.ink2}>G_in = U/(1−f)</text>
      {/* solar */}
      <g stroke="#d9a400" strokeWidth="2"><line x1="10" y1="40" x2="68" y2="62" /><polygon points="64,56 70,63 62,66" fill="#d9a400" /></g>
      <text x="20" y="36" fontSize="10" fill="#b58800" fontWeight="700">α·I</text>
      {/* sky */}
      <g stroke={C.cold} strokeWidth="2"><line x1="68" y1="150" x2="10" y2="180" /><polygon points="14,174 8,182 18,182" fill={C.cold} /></g>
      <text x="14" y="200" fontSize="10" fill={C.cold} fontWeight="700">ε σ (T⁴−T_sky⁴)</text>
      {/* vent stream warming the pane */}
      <g stroke={C.water} strokeWidth="2"><path d="M250 70 H 120 V 100" fill="none" /><polygon points="116,96 120,104 124,96" fill={C.water} /></g>
      <text x="170" y="64" textAnchor="middle" fontSize="10" fill={C.water} fontWeight="700">ṁ·c_p → h_cold</text>
      <text x="146" y="190" textAnchor="middle" fontSize="10" fill={C.ink2}>cavity</text>
    </svg>
  )
}

function FigSources({ c }) {
  // Two arrows into the cavity, widths by |net|, pointing OUT when negative.
  const out = c?.outdoor_g ?? 0, room = c?.room_g ?? 0
  const big = Math.max(Math.abs(out), Math.abs(room), 1e-9)
  const w = (g) => 2 + 8 * Math.abs(g) / big
  const outArrow = out >= 0 ? { x1: 50, x2: 118, tip: '118,74 134,84 118,94' } : { x1: 134, x2: 66, tip: '66,74 50,84 66,94' }
  const roomArrow = room >= 0 ? { x1: 250, x2: 182, tip: '182,120 166,130 182,140' } : { x1: 166, x2: 234, tip: '234,120 250,130 234,140' }
  return (
    <svg viewBox="0 0 300 200">
      <rect x="0" y="0" width="90" height="200" fill="#e6edf5" /><rect x="210" y="0" width="90" height="200" fill="#f4f1ea" />
      <rect x="90" y="0" width="8" height="200" fill={C.cold} /><rect x="202" y="0" width="8" height="200" fill="#c9d8ea" />
      <text x="45" y="20" textAnchor="middle" fontSize="11" fill={C.ink2}>outdoor</text><text x="255" y="20" textAnchor="middle" fontSize="11" fill={C.ink2}>room</text>
      <line x1={outArrow.x1} y1="84" x2={outArrow.x2} y2="84" stroke={C.cold} strokeWidth={w(out)} strokeLinecap="round" /><polygon points={outArrow.tip} fill={C.cold} />
      <line x1={roomArrow.x1} y1="130" x2={roomArrow.x2} y2="130" stroke={C.water} strokeWidth={w(room)} strokeLinecap="round" /><polygon points={roomArrow.tip} fill={C.water} />
      <text x="150" y="60" textAnchor="middle" fontSize="11" fill={C.cold} fontWeight="700">{out >= 0 ? 'adds' : 'removes'} {fmt.n(Math.abs(out), Math.abs(out) < 10 ? 1 : 0)} g</text>
      <text x="150" y="160" textAnchor="middle" fontSize="11" fill={C.water} fontWeight="700">{room >= 0 ? 'adds' : 'removes'} {fmt.n(Math.abs(room), Math.abs(room) < 10 ? 1 : 0)} g</text>
      <text x="150" y="110" textAnchor="middle" fontSize="11" fill={C.ink2}>net, over the window</text>
    </svg>
  )
}

function FigCondense() {
  return (
    <svg viewBox="0 0 300 200">
      <rect x="40" y="20" width="10" height="160" fill={C.cold} />
      <rect x="50" y="80" width="4" height="100" fill={C.fog} />
      <text x="45" y="195" textAnchor="middle" fontSize="10" fill={C.ink2}>pane T_cold</text>
      <g fill={C.water}>{[70, 100, 130].map((y) => <circle key={y} cx="120" cy={y} r="4" />)}</g>
      <g stroke={C.water} strokeWidth="1.5">{[70, 100, 130].map((y) => <line key={y} x1="112" y1={y} x2="60" y2={y + 10} />)}</g>
      <text x="150" y="70" fontSize="11" fill={C.ink2}>W_cav &gt; W_sat(T_cold)</text>
      <text x="150" y="88" fontSize="11" fill={C.fog}>→ film grows</text>
      <text x="150" y="120" fontSize="11" fill={C.ink2}>W_cav &lt; W_sat(T_cold)</text>
      <text x="150" y="138" fontSize="11" fill={C.water}>→ film dries</text>
      <text x="150" y="170" fontSize="11" fill={C.ink2}>film capped at 100 µm, rest drains</text>
    </svg>
  )
}

function FigIsotherm({ des }) {
  if (!des) return null
  const pts25 = des.isotherm_25c, pts60 = des.isotherm_60c
  const x = (rh) => 30 + (rh / 100) * 250, y = (q) => 170 - (q / 25) * 140
  const path = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.rh_pct)} ${y(p.q_pct)}`).join(' ')
  return (
    <svg viewBox="0 0 300 200">
      <line x1="30" y1="170" x2="280" y2="170" stroke={C.line} /><line x1="30" y1="30" x2="30" y2="170" stroke={C.line} />
      <path d={path(pts25)} fill="none" stroke={C.sand} strokeWidth="2.5" />
      <path d={path(pts60)} fill="none" stroke={C.fog} strokeWidth="2" strokeDasharray="4 3" />
      <text x="150" y="190" textAnchor="middle" fontSize="10" fill={C.ink2}>relative humidity, 0 to 100 %</text>
      <text x="12" y="100" textAnchor="middle" fontSize="10" fill={C.ink2} transform="rotate(-90 12 100)">loading, % by mass</text>
      <text x="200" y="50" fontSize="11" fill={C.sand} fontWeight="700">25 °C</text>
      <text x="200" y="80" fontSize="11" fill={C.fog} fontWeight="700">60 °C</text>
    </svg>
  )
}

function FigLife({ h }) {
  const ex = h?.exhausted_hour, fc = h?.first_condensation_hour
  const tot = Math.max(ex || 0, fc || 0, 1)
  const x = (v) => 20 + (v / tot) * 250
  return (
    <svg viewBox="0 0 300 120">
      <line x1="20" y1="60" x2="280" y2="60" stroke={C.line} strokeWidth="6" strokeLinecap="round" />
      {ex !== null && ex !== undefined && <><line x1="20" y1="60" x2={x(ex)} y2="60" stroke={C.sand} strokeWidth="6" strokeLinecap="round" /><text x={x(ex)} y="45" textAnchor="middle" fontSize="11" fill={C.sand} fontWeight="700">full</text></>}
      {fc !== null && fc !== undefined && <><circle cx={x(fc)} cy="60" r="7" fill={C.fog} /><text x={x(fc)} y="88" textAnchor="middle" fontSize="11" fill={C.fog} fontWeight="700">first fog</text></>}
      <text x="20" y="108" fontSize="10" fill={C.ink2}>hour 0</text><text x="280" y="108" textAnchor="end" fontSize="10" fill={C.ink2}>hour {fmt.n(tot)}</text>
    </svg>
  )
}

/* ---- page ------------------------------------------------------------- */

export default function Explain({ result, presets, inp }) {
  const i = result?.inputs, h = result?.headline, y1 = result?.year1, pr = result?.pressure
  const des = presets?.desiccants?.find((d) => d.key === (i?.desiccant || 'ms3a'))
  const volL = i ? (i.width_in * i.height_in * i.offset_in * 16.387) / 1000 : null
  const airKg = volL ? volL * 1.2 / 1000 : null
  const maxRise = y1 ? Math.max(...y1.vent_rise_f) : null

  return (
    <div className="explain">
      <div className="card">
        <h2>What the simulator does, step by step</h2>
        <p className="lede">Seven pieces of physics, each with its formula and the numbers from your current run. Nothing here is fitted to make the answer come out a particular way; the estimates are listed at the end.</p>

        <Step title="1. The cavity holds a small inventory of water" figure={<FigInventory w={i?.width_in ?? inp.width_in} h={i?.height_in ?? inp.height_in} off={i?.offset_in ?? inp.offset_in} />}>
          <p>The state variable is the humidity ratio W of the cavity air, in kg of water per kg of dry air. W is used instead of RH because it is conserved when the air changes temperature; you can write a mass balance in W, not in RH.</p>
          <div className="formula">{`m_air = width × height × offset × ρ_air\nwater in cavity = m_air × W_cav`}</div>
          {i && <Live rows={[['Cavity volume', `${fmt.n(volL, 1)} L`], ['Dry air mass', `${fmt.n(airKg * 1000, 1)} g`], ['Water at room humidity', `${fmt.n(airKg * 5.5, 3)} g`]]} />}
        </Step>

        <Step title="2. One air stream passes through it" figure={<FigStreams aOut={i?.ach_out ?? '—'} aIn={i?.ach_in ?? '—'} />}>
          <p>The existing window and the retrofit are two leaks in series on one path. There is a single pressure difference between the room and outdoors each hour, the cavity floats to a pressure in between, and the same air enters through one layer and leaves through the other. The tighter layer takes most of the pressure and sets how much air moves; the sign of the pressure sets which air it is. Room-side pressure comes from HVAC pressurisation and from stack above the neutral plane in winter; outdoor-side pressure from wind on the facade and stack below the neutral plane.</p>
          <div className="formula">{`ΔP(h) = P_HVAC(h) + (ρ_out − ρ_in)·g·h_NPL − ½ρv(h)²·C_p(θ)          room minus outdoors\nq(h)  = |ΔP|^0.65 / (C_out^(−1/0.65) + C_in^(−1/0.65))^0.65     series, C = AL·18.29/75^0.65\nΔP > 0: room air in through the retrofit      ΔP < 0: outdoor air in through the existing window\nW(t+dt) = W_supply + (W − W_supply) · exp(−ACH·dt)`}</div>
          <p>For a wet-sealed retrofit behind an operable old window the retrofit is about 60× tighter, takes 98 % of the pressure, and the through-flow is within 3 % of what the retrofit alone would pass at the full ΔP. Opening the old window's leakage further changes almost nothing; it is not the restriction. That is why the retrofit seal, and once it is airtight the sealant's vapour permeability, set the desiccant life. A deeper cavity dilutes the same flow into more air, so ACH falls with offset but the water arriving per hour does not, and desiccant life does not either. The third path is vapour diffusion through the sealant bead, J = P·A·Δp_v / L, a constant trickle that becomes the floor once air leakage reaches zero: about 0.035 g/day for a 1/4 in silicone bead, 100× less for PIB. Thermal breathing (the cavity contracting as it cools) is the only two-sided exchange, about 0.003 ACH per 1 K hourly drop.</p>
          {i && <Live rows={[['Existing window', `${i.al_out ?? '—'} cfm/ft² (${fmt.g(i.ach_out)} ACH alone at ${i.dp_pa} Pa)`], ['Retrofit', `${i.al_in ?? '—'} cfm/ft² (${fmt.g(i.ach_in)} ACH alone at ${i.dp_pa} Pa)`], ['HVAC pressure occupied / unoccupied', `${i.p_occ_pa} / ${i.p_unocc_pa} Pa`], ['Window height above neutral plane', `${i.height_above_npl_ft} ft`], ['Mean through-flow over the year', `${fmt.g(pr?.mean_ach)} ACH`], ['Hours room-fed / outdoor-fed / still', `${pr?.hours_room_fed ?? '—'} / ${pr?.hours_outdoor_fed ?? '—'} / ${pr?.hours_neutral ?? '—'}`], ['Signed ΔP range', `${pr?.min_dp_pa ?? '—'} to ${pr?.max_dp_pa ?? '—'} Pa, mean |ΔP| ${pr?.mean_abs_dp_pa ?? '—'} Pa`], ['Wind direction in weather file', pr?.wind_direction_available ? 'yes' : 'no, every windy hour treated as windward'], ['Bead diffusion, room side', `${i.diffusion_g_per_day} g/day`], ['Air through the cavity per hour, mean', `${fmt.n((pr?.mean_ach ?? 0) * airKg * 1000, 1)} g`]]} />}
        </Step>

        <Step title="3. The existing pane's temperature" figure={<FigEnergy />}>
          <p>The pane's cavity face sits at a fraction f of the way from outdoor to room temperature, set by the assembly's resistances. Sun warms it, a clear night sky cools it, and the vent streams pull it toward whichever air they carry. The vent term is small and is an upper bound.</p>
          <div className="formula">{`T_cold = T_out + f · (T_room − T_out)\n       + α·I / h_out                      sun\n       − ε σ F (T⁴ − T_sky⁴) / h_out          sky\n       + [G_in_v (T_room − T) + G_out_v (T_out − T)] / (G_out + G_in + G_in_v + G_out_v)\n  with G_out = U/f, G_in = U/(1−f), G_vent = 1/(1/(ṁ c_p) + 1/h_cold)`}</div>
          {i && <Live rows={[['f_cold', i.f_cold], ['U', `${i.u_ip} Btu/hr·ft²·°F`], ['Largest vent warming this year', `${fmt.n(maxRise, 2)} °F`]]} />}
        </Step>

        <Step title="4. Condensation and drying at the pane" figure={<FigCondense />}>
          <p>Air cannot hold more water than saturation at the coldest surface it touches. Whatever arrives above that line deposits as a film; when conditions ease the film evaporates back. Supply and deposition happen at the same time, so the hour is solved in closed form rather than split.</p>
          <div className="formula">{`condensing when  W_supply > W_sat(T_cold)\nrate = (ACH_out + ACH_in) · m_air · (W_supply − W_sat)      kg/h\nfilm capped at 100 µm; beyond that it runs off and is gone`}</div>
          {h && <Live rows={[['Hours condensing, year 1', fmt.n(result.years[0].hours_condensing)], ['Condensed, year 1', `${fmt.n(1000 * result.years[0].condensed_kg_per_m2, 1)} g/m²`]]} />}
        </Step>

        <Step title="5. The desiccant follows its isotherm" figure={<FigIsotherm des={des} />}>
          <p>A 3A sieve holds a fraction q of its own mass in water. q depends on the humidity around it (Langmuir shape: steep at low RH, flat above 30 %) and drops with temperature. It approaches that equilibrium with a time constant, hours not minutes, because beads are slow inside and a cartridge limits air contact.</p>
          <div className="formula">{`q_eq(RH, T) = q_max(T) · K(T)·RH / (1 + K(T)·RH)\nq(t+dt) = q_eq + (q − q_eq) · exp(−dt/τ)\nwater removed = (q_new − q) · m_desiccant`}</div>
          <p>The inverse matters just as much: a sieve at loading q holds the air at RH_eq(q). Half full, that is about 1 %. At 95 % full it is 15 to 30 %, which is why a sieve stops protecting the pane before it is "full".</p>
          {i && des && <Live rows={[['Capacity at 25 °C', `${fmt.n(100 * des.q_max_25, 0)} % by mass`], ['Your mass holds', `${fmt.n(i.capacity_g, 1)} g`], ['Time constant', `${i.tau_h} h`], ['Cartridge volume', `${i.cartridge_ml} mL`], ['Give water back when hot', i.desorption ? 'on' : 'off']]} />}
        </Step>

        <Step title="6. End of life and hours per gram" figure={<FigLife h={h} />}>
          <p>Two numbers. The sieve is called full at 95 % of its 25 °C capacity, because a Langmuir curve reaches 100 % only asymptotically; at 35 % room RH its equilibrium is 96.7 %, so thresholds above that would never fire. First fog is the first hour any water condenses on the pane; it can come before or after full, depending on how cold the pane runs.</p>
          <div className="formula">{`exhausted_hour = first hour q ≥ 0.95 · q_max(25 °C)\nhours_per_gram = exhausted_hour / grams\ngrams for one year ≈ 8760 / hours_per_gram`}</div>
          {h && <Live rows={[['Full after', h.exhausted_hour === null ? 'not within run' : `${fmt.n(h.exhausted_hour)} h`], ['First fog', h.first_condensation_hour === null ? 'none' : `${fmt.n(h.first_condensation_hour)} h`], ['Hours per gram', h.hours_per_gram ?? '—']]} />}
        </Step>

        <Step title="7. Where the water comes from" figure={<FigSources c={result?.contributions ? scaleWindow(result.contributions.life, result.contributions.life_hours) : null} />}>
          <p>The supply in step 2 is a flow-weighted mix, so the water each path delivers can be split exactly. What matters is the sign: each path pushes the cavity toward its own humidity, so a path whose air is <em>drier</em> than the cavity carries water out. Cold outdoor air holds little water even at high RH, so in winter the outdoor path is usually a remover while the room path is the source, and the sum of the three is what the sieve and the pane took.</p>
          <div className="formula">{`N_out  = ACH_out · m_air · (W_out − W_cav) · dt
N_in   = ACH_in  · m_air · (W_room − W_cav) · dt
N_bead = J · dt
N_out + N_in + N_bead = into sieve + onto pane + Δ(cavity air)
N_out < 0 whenever W_out < W_cav: outdoor air carries water out`}</div>
          <p>A fresh sieve pulls the cavity to near zero humidity, so while it fills <em>every</em> path is a source, even the coldest outdoor air. Once the sieve is full or absent, the cavity rides at the mixed supply and the winter drying shows: over a year the two paths nearly cancel, so the year table also lists the October to March outdoor net on its own.</p>
          {result?.contributions && <>
            <SourceBar c={scaleWindow(result.contributions.life, result.contributions.life_hours)} height={12} />
            <SourceLegend c={scaleWindow(result.contributions.life, result.contributions.life_hours)} compact />
          </>}
          {result?.years?.[0] && <Live rows={[
            ['Life window', result.headline.exhausted_hour !== null ? `${fmt.n(result.contributions.life_hours)} h to full` : `${result.headline.years_run} yr run`],
            ['Year 1, Oct–Mar outdoor net', `${fmt.n(result.years[0].heating_outdoor_g, 1)} g`],
            ['Year 1, Oct–Mar room net', `${fmt.n(result.years[0].heating_room_g, 1)} g`],
            ['Year 1, full-year outdoor net', `${fmt.n(result.years[0].net_outdoor_g, 1)} g`],
            ['Year 1, full-year room net', `${fmt.n(result.years[0].net_room_g, 1)} g`],
          ]} />}
        </Step>

        <section className="step" style={{ gridTemplateColumns: '1fr', borderBottom: 0 }}>
          <div>
            <h3>What is estimated, not measured</h3>
            <ol className="assume">{(result?.assumptions || presets?.assumptions || []).map((a) => <li key={a}>{a}</li>)}</ol>
          </div>
        </section>
      </div>
    </div>
  )
}
