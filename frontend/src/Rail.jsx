import { achFromAL, fmt } from './api.js'

function Num({ label, k, inp, set, step = 1, min, max, unit }) {
  return (
    <div className="field">
      <label htmlFor={k}>{label}{unit && <> <span className="unit">{unit}</span></>}</label>
      <input id={k} type="number" step={step} min={min} max={max} value={inp[k]} onChange={(e) => set(k, e.target.value === '' ? '' : Number(e.target.value))} />
    </div>
  )
}

function Ladder({ k, inp, set, presets, note }) {
  const cur = inp[k]
  const active = (p) => cur === p.key || Number(cur) === p.al_cfm_ft2
  const value = typeof cur === 'number' ? cur : (presets.find((p) => p.key === cur)?.al_cfm_ft2 ?? '')
  const ach = achFromAL(Number(value), Number(inp.dp_pa), Number(inp.offset_in))
  const sel = presets.find((p) => active(p))
  return (
    <>
      <div className="ladder">
        {presets.map((p) => (
          <button key={p.key} type="button" aria-pressed={active(p)} title={`${p.al_cfm_ft2} cfm/ft² at 75 Pa. ${p.source}`} onClick={() => set(k, p.key)}>
            {p.label}{p.estimate ? '' : ' ✓'}
          </button>
        ))}
      </div>
      <div className="field">
        <label>Air leakage <span className="unit">cfm/ft² at 75 Pa</span></label>
        <input type="number" step="0.01" min="0" value={value} onChange={(e) => set(k, Number(e.target.value))} />
      </div>
      <div className="field derived">
        <label>Cavity air changes <span className="unit">derived</span></label>
        <output>{Number.isFinite(ach) ? `${fmt.g(ach)} ACH` : ''}</output>
      </div>
      <p className="hint">{sel ? sel.source : 'Custom value.'} {note}</p>
    </>
  )
}

function Check({ label, k, inp, set }) {
  return (
    <label className="check"><input type="checkbox" checked={!!inp[k]} onChange={(e) => set(k, e.target.checked)} />{label}</label>
  )
}

export default function Rail({ inp, set, presets, busy, onRun }) {
  const volumeL = (inp.width_in * inp.height_in * inp.offset_in * 16.387) / 1000
  const des = presets?.desiccants?.find((d) => d.key === inp.desiccant)
  const capG = des ? inp.grams * des.q_max_25 : null
  return (
    <aside className="rail">
      <form onSubmit={(e) => { e.preventDefault(); onRun() }}>
        <div className="group">
          <h3>Location</h3>
          <div className="field wide"><input type="text" value={inp.address} onChange={(e) => set('address', e.target.value)} aria-label="Address" /></div>
          <div className="field"><label>Facade faces</label>
            <select value={inp.orientation} onChange={(e) => set('orientation', e.target.value)}>
              {(presets?.orientations || ['south']).map((o) => <option key={o} value={o}>{o}</option>)}
            </select></div>
          <p className="hint">Typical meteorological year from the nearest NSRDB grid cell.</p>
        </div>

        <div className="group">
          <h3>Cavity<span>{fmt.n(volumeL, 1)} L of air</span></h3>
          <Num label="Width" k="width_in" unit="in" inp={inp} set={set} min={1} />
          <Num label="Height" k="height_in" unit="in" inp={inp} set={set} min={1} />
          <Num label="Offset" k="offset_in" unit="in" inp={inp} set={set} step={0.05} min={0.05} />
          <Num label="Cold-surface f" k="f_cold" inp={inp} set={set} step={0.01} min={0} max={1} />
          <Num label="Assembly U" k="u_ip" unit="Btu/hr·ft²·°F" inp={inp} set={set} step={0.01} min={0.01} />
          <Num label="Cavity R" k="r_ip" unit="hr·ft²·°F/Btu" inp={inp} set={set} step={0.01} min={0.01} />
          <p className="hint">f is the temperature factor of the existing pane's cavity face, from WINDOW or THERM. The warm-surface f is estimated from U and R unless you set it.</p>
        </div>

        <div className="group">
          <h3>Existing window<span>leakage from outdoors</span></h3>
          {presets && <Ladder k="al_out" inp={inp} set={set} presets={presets.al_out} note="✓ marks a published number." />}
          <Check label="Add wind pressure hour by hour" k="wind_scaling" inp={inp} set={set} />
        </div>

        <div className="group">
          <h3>Retrofit<span>leakage from the room</span></h3>
          {presets && <Ladder k="al_in" inp={inp} set={set} presets={presets.al_in} note="Type the value from an AERC certificate or test report." />}
          <Num label="Operating pressure" k="dp_pa" unit="Pa" inp={inp} set={set} step={0.5} min={0} max={75} />
          <p className="hint">Ratings are measured at 75 Pa. A cavity sees about 2 to 6 Pa of stack and wind; flow scales with pressure^0.65. <a href={presets?.leakage_reference?.aerc_url} target="_blank" rel="noreferrer">AERC certified product search</a></p>
        </div>

        <div className="group">
          <h3>Room</h3>
          <Num label="Temperature" k="t_in" unit="°F" inp={inp} set={set} min={40} max={100} />
          <Num label="Relative humidity" k="rh_in" unit="%" inp={inp} set={set} min={0} max={100} />
        </div>

        <div className="group">
          <h3>Desiccant<span>{capG !== null ? `holds ${fmt.n(capG, 1)} g of water` : ''}</span></h3>
          <div className="field"><label>Type</label>
            <select value={inp.desiccant} onChange={(e) => set('desiccant', e.target.value)}>
              {(presets?.desiccants || []).map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
            </select></div>
          <Num label="Mass" k="grams" unit="g" inp={inp} set={set} min={0} step={5} />
          <Num label="Time constant" k="tau_h" unit="h" inp={inp} set={set} min={0.01} step={0.5} />
          <Check label="Let it give water back when hot and dry" k="desorption" inp={inp} set={set} />
          <p className="hint">Isotherm constants are fitted to published 3A curves.<span className="est">estimate</span></p>
        </div>

        <div className="group">
          <h3>Physics</h3>
          <Num label="Solar absorptance" k="absorptance" inp={inp} set={set} step={0.01} min={0} max={1} />
          <p className="hint">Sun warms the existing pane in proportion. 0 switches the sun off.</p>
          <Check label="Clear night sky cools the pane" k="sky_radiation" inp={inp} set={set} />
          <Check label="Vent air warms the pane" k="pane_coupling" inp={inp} set={set} />
          <Num label="Run up to" k="max_years" unit="years" inp={inp} set={set} min={1} max={50} />
        </div>

        <button className="btn primary run" type="submit" disabled={busy}>{busy ? 'Running…' : 'Run simulation'}</button>
      </form>
    </aside>
  )
}
