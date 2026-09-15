import { achFromAL, fmt } from './api.js'
import { Tip } from './Tip.jsx'

function Num({ label, k, inp, set, step = 1, min, max, unit, tip = k }) {
  return (
    <div className="field">
      <label htmlFor={k}>{label}{unit && <> <span className="unit">{unit}</span></>} <Tip id={tip} /></label>
      <input id={k} type="number" step="any" min={min} max={max} value={inp[k]} onChange={(e) => set(k, e.target.value === '' ? '' : Number(e.target.value))} />
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
        <label>Air leakage <span className="unit">cfm/ft² at 75 Pa</span> <Tip id={k} /></label>
        <input type="number" step="any" min="0" value={value} onChange={(e) => set(k, Number(e.target.value))} />
      </div>
      <div className="field derived">
        <label>Cavity air changes <span className="unit">derived</span> <Tip id="ach_derived" /></label>
        <output>{Number.isFinite(ach) ? `${fmt.g(ach)} ACH` : ''}</output>
      </div>
      <p className="hint">{sel ? sel.source.replace(/\.?$/, '.') : 'Custom value.'} {note}</p>
    </>
  )
}

function Check({ label, k, inp, set }) {
  return (
    <div className="check"><label><input type="checkbox" checked={!!inp[k]} onChange={(e) => set(k, e.target.checked)} />{label}</label> <Tip id={k} /></div>
  )
}

export default function Rail({ inp, set, presets, busy, onRun, onClose }) {
  const volumeL = (inp.width_in * inp.height_in * inp.offset_in * 16.387) / 1000
  const des = presets?.desiccants?.find((d) => d.key === inp.desiccant)
  const capG = des ? inp.grams * des.q_max_25 : null
  return (
    <aside className="rail">
      <form onSubmit={(e) => { e.preventDefault(); onRun() }}>
        <div className="rail-head"><span>Inputs</span><button type="button" className="btn small" onClick={onClose}>Hide</button></div>
        <div className="group">
          <h3>Location</h3>
          <div className="field wide"><label htmlFor="address">Address <Tip id="address" /></label><input id="address" type="text" value={inp.address} onChange={(e) => set('address', e.target.value)} /></div>
          <div className="field"><label>Facade faces <Tip id="orientation" /></label>
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
          <p className="hint">Ratings are measured at 75 Pa; a cavity sees a few Pa. The two layers are in series: the tighter one sets the flow, the sign of the pressure sets which air comes in. <a href={presets?.leakage_reference?.aerc_url} target="_blank" rel="noreferrer">AERC certified product search</a></p>
        </div>

        <div className="group">
          <h3>Building<span>signed pressure, room minus outdoors</span></h3>
          <Num label="HVAC pressure, occupied" k="p_occ_pa" unit="Pa" inp={inp} set={set} step={0.5} min={-75} max={75} />
          <Num label="HVAC pressure, unoccupied" k="p_unocc_pa" unit="Pa" inp={inp} set={set} step={0.5} min={-75} max={75} />
          <Num label="Occupied from" k="occ_start_h" unit="h" inp={inp} set={set} min={0} max={24} />
          <Num label="Occupied until" k="occ_end_h" unit="h" inp={inp} set={set} min={0} max={24} />
          <Check label="Weekdays only" k="weekdays_only" inp={inp} set={set} />
          <Num label="Storeys" k="floors" inp={inp} set={set} min={1} max={200} />
          <Num label="Window on floor" k="window_floor" inp={inp} set={set} min={1} max={200} />
          <Num label="Floor height" k="floor_height_ft" unit="ft" inp={inp} set={set} step={0.1} min={6} max={30} />
          <Check label="Single-sided loops (chimney through each layer)" k="loops" inp={inp} set={set} />
          <Num label="Crack placement k" k="loop_k" inp={inp} set={set} step={0.05} min={0} max={1} />
          <Num label="Loop flow exponent" k="loop_n" inp={inp} set={set} step={0.05} min={0.5} max={1} />
          <Check label="Thermal breathing" k="breathing" inp={inp} set={set} />
          <Check label="Series model (off = legacy parallel)" k="series_model" inp={inp} set={set} />
          <p className="hint">Positive pushes room air into the cavity, negative pulls outdoor air in. Wind is added by direction against the facade orientation above; stack from the floor position. Each layer also breathes with its own side through its own cracks (the loop), so both seals matter.</p>
          <Num label="Reference pressure for the ACH readouts" k="dp_pa" unit="Pa" inp={inp} set={set} step={0.5} min={0} max={75} />
        </div>

        <div className="group">
          <h3>Seals<span>vapour through the bead</span></h3>
          <div className="field"><label>Existing window <Tip id="sealant_out" /></label>
            <select value={inp.sealant_out} onChange={(e) => set('sealant_out', e.target.value)}>
              {(presets?.sealants || []).map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
            </select></div>
          <div className="field"><label>Retrofit <Tip id="sealant_in" /></label>
            <select value={inp.sealant_in} onChange={(e) => set('sealant_in', e.target.value)}>
              {(presets?.sealants || []).map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
            </select></div>
          <Num label="Bead width" k="bead_width_in" unit="in" inp={inp} set={set} min={0} />
          <Num label="Bead depth" k="bead_depth_in" unit="in" inp={inp} set={set} min={0.02} />
          <p className="hint">Silicone stops air but passes water vapour about 100× faster than the polyisobutylene an IGU uses. This is the floor once air leakage is at zero.</p>
        </div>

        <div className="group">
          <h3>Room</h3>
          <Num label="Temperature" k="t_in" unit="°F" inp={inp} set={set} min={40} max={100} />
          <Num label="Relative humidity" k="rh_in" unit="%" inp={inp} set={set} min={0} max={100} />
        </div>

        <div className="group">
          <h3>Desiccant<span>{capG !== null ? `holds ${fmt.n(capG, 1)} g of water` : ''}</span></h3>
          <div className="field"><label>Type <Tip id="desiccant" /></label>
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
