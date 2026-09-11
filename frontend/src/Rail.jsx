import { fmt } from './api.js'

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
  const active = (p) => cur === p.key || Number(cur) === p.value
  return (
    <>
      <div className="ladder">
        {presets.map((p) => (
          <button key={p.key} type="button" aria-pressed={active(p)} title={p.label} onClick={() => set(k, p.key)}>
            {p.key.replace('_', ' ')}
          </button>
        ))}
      </div>
      <div className="field">
        <label>Value <span className="unit">ACH</span></label>
        <input type="number" step="0.001" min="0" value={typeof cur === 'number' ? cur : (presets.find((p) => p.key === cur)?.value ?? '')} onChange={(e) => set(k, Number(e.target.value))} />
      </div>
      <p className="hint">{note}</p>
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
          <h3>Outdoor leakage<span>through the existing window</span></h3>
          {presets && <Ladder k="ach_out" inp={inp} set={set} presets={presets.ach_out} note="Air changes of the cavity volume per hour, at 4 m/s wind." />}
          <Check label="Scale with hourly wind speed" k="wind_scaling" inp={inp} set={set} />
        </div>

        <div className="group">
          <h3>Room-side vent<span>through the retrofit</span></h3>
          {presets && <Ladder k="ach_in" inp={inp} set={set} presets={presets.ach_in} note="Deliberate vent or perimeter leakage into the room." />}
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
