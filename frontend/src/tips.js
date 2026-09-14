// Every input and output, three parts: what it is, how the model uses it,
// where the default or the number comes from. Engineering register.
// Keys match input names in api.js DEFAULT_INPUTS or output ids used in Simulate.

export const TIPS = {
  // ---------------------------------------------------------------- location
  address: {
    what: 'Street address of the building. Geocoded (Mapbox) to a lat/lon, then matched to the nearest NSRDB grid cell.',
    how: 'Selects the typical meteorological year (TMY, 8,760 h) of outdoor dry-bulb, RH, wind, GHI/DNI/DHI and cloud type that drives every hour of the run. The year is repeated until the sieve is full.',
    src: 'NSRDB GOES TMY v4, 4 km cells. Default 277 Park Avenue, the ANLY-002 reference site.',
  },
  orientation: {
    what: 'Compass direction the facade faces.',
    how: 'Sets the tilt/azimuth used to project GHI/DNI/DHI onto the vertical plane (plane-of-array irradiance) for the solar term on the existing pane.',
    src: 'Default south. Orientation moves fill time by 0 % and first-fog hour by up to a day (AUDIT §1 row 13).',
  },
  // ---------------------------------------------------------------- cavity
  width_in: {
    what: 'Clear width of the glazed cavity, inches.',
    how: 'With height: glazing area. The engine works per m² of glass; desiccant grams per window are divided by this area, and results scale back.',
    src: 'Default 60 in, a common commercial lite. Per-area scaling is tested (test_properties::test_per_area_scaling).',
  },
  height_in: {
    what: 'Clear height of the glazed cavity, inches.',
    how: 'As width. Also the stack height for buoyancy pressure, though the model takes operating pressure as an input rather than computing it.',
    src: 'Default 96 in. Stack pressure over 8 ft at 25 K ≈ 2.5 Pa (engine/leakage.py).',
  },
  offset_in: {
    what: 'Air gap between the existing pane and the retrofit IGU, inches.',
    how: 'Cavity volume per m² = offset. Sets air mass (m_cav) and converts rated leakage to ACH (ACH = flow / offset). It does NOT change desiccant life: crack flow per m² of window is fixed by the rating, so a deeper cavity has lower ACH but the same water arriving per hour.',
    src: 'Default 0.6 in (15.2 mm), close to the ANLY-002 reference of 0.6024 in. Offset invariance is tested (test_properties::test_offset_does_not_change_fill_time).',
  },
  f_cold: {
    what: 'Temperature factor of the existing pane\'s cavity-side face: f = (T_surface − T_out) / (T_room − T_out), dimensionless, 0 = at outdoor temperature.',
    how: 'T_cold = T_out + f·(T_room − T_out) every hour, then solar, sky and vent corrections. T_cold sets W_sat at the pane, the condensation threshold.',
    src: 'From a THERM/WINDOW model or ISO 15099 hand calc of the assembly. Default 0.30 (ANLY-002 277 Park case). For an IGU retrofit over single glass, f_cold is typically 0.2 to 0.4.',
  },
  u_ip: {
    what: 'Whole-assembly U-factor, Btu/hr·ft²·°F (existing window + cavity + retrofit).',
    how: 'Gives the absolute scale of the pane\'s conductances: G_out = U/f, G_in = U/(1−f). Needed for the vent-warming term and the warm-surface estimate. Converted to W/m²K internally (×5.678).',
    src: 'Default 0.30 (1.70 W/m²K), ANLY-002. From NFRC/AERC rating or THERM.',
  },
  r_ip: {
    what: 'Thermal resistance of the cavity air layer alone, hr·ft²·°F/Btu.',
    how: 'Used only to estimate the warm-surface factor f_warm from f_cold and U when f_warm is not given: f_warm = f_cold + R_cav·U. f_warm sets the retrofit\'s cavity-side temperature, which enters the cavity air temperature.',
    src: 'Default 0.97 (0.17 m²K/W), a 15 mm still-air gap per ISO 6946. Set f_warm directly if you have it.',
  },
  // ---------------------------------------------------------------- leakage
  al_out: {
    what: 'Rated air leakage of the EXISTING window, cfm/ft² of window area at a 75 Pa test pressure (ASTM E283 / NFRC 400, the AERC certificate number).',
    how: 'Converted to cavity ACH each hour: ACH = AL × 18.29 × (ΔP/75)^0.65 / offset, with ΔP = operating pressure plus wind stagnation pressure when wind scaling is on. Outdoor air enters at outdoor humidity ratio W_out.',
    src: 'Published anchors: AERC baseline single-pane 2.0; new fixed commercial spec 0.06 (ticked). Values between are estimates. Uncertainty on the derived ACH ≈ factor 3 (AUDIT §3.1).',
  },
  wind_scaling: {
    what: 'Add wind stagnation pressure to the outdoor path\'s operating pressure hour by hour.',
    how: 'ΔP_out(h) = dp_pa + 0.5·ρ·v(h)²·Cp with Cp = 0.6 (windward face). Flow scales as ΔP^0.65. Room path unchanged.',
    src: 'NSRDB 2 m wind. Effect on fill time −20 to −50 % when on (AUDIT §1 row 4). Default on.',
  },
  al_in: {
    what: 'Rated air leakage of the RETROFIT (the secondary window), cfm/ft² at 75 Pa.',
    how: 'Same conversion as the existing window. Room air enters at the room humidity ratio W_room = f(T_room, RH_room). Supply humidity to the cavity is the flow-weighted mix of both streams.',
    src: 'AERC best certified insert 0.06 (Alpen WinSert, Dec 2021, ticked). Wet-sealed 0.005 is the ASTM E283 detection floor, the INOVUES practice (continuous silicone bead), an estimate until a cavity pressurisation test replaces it. Below the floor, sealant diffusion takes over.',
  },
  dp_pa: {
    what: 'Operating pressure difference across each layer, Pa.',
    how: 'Scales the rated leakage from the 75 Pa test to service conditions via (ΔP/75)^0.65. Applied to both layers (in series the tighter one takes most of the total).',
    src: 'Default 3 Pa: stack over 8 ft at 25 K ≈ 2.5 Pa, wind at 4 m/s ≈ 5.8 Pa (added separately). Fill time ±25 % for 1.5 to 6 Pa; the largest single uncertainty (AUDIT §1 row 1).',
  },
  sealant_out: {
    what: 'Sealant used to wet-seal the existing window on its cavity side.',
    how: 'Water vapour diffuses through the bead: J = P · (perimeter × bead width) · Δp_v / bead depth, with the cavity taken as dry (upper bound). Added to the supply as a constant trickle at the outdoor vapour pressure.',
    src: 'Silicone permeability 30 g·mm/m²/day at the ASTM E96 condition (published range 20 to 40); PIB 0.3. ESTIMATES. DOWSIL 795 class is the common weatherseal.',
  },
  sealant_in: {
    what: 'Sealant used on the retrofit frame perimeter.',
    how: 'Same diffusion law, at the room vapour pressure. A 1/4 × 1/4 in silicone bead on a 60 × 96 in window passes about 0.035 g/day at 70 °F / 35 % RH; PIB about 0.0003.',
    src: 'ASTM E96 ranges. With zero air leakage the silicone floor fills 1 kg of 3A in about 6.6 years; PIB beyond 20.',
  },
  bead_width_in: {
    what: 'Joint width the bead bridges, inches. Sets the exposed diffusion area (perimeter × width).',
    how: 'Diffusion scales linearly with it.',
    src: 'ASTM C1193 minimum joint 1/4 in.',
  },
  bead_depth_in: {
    what: 'Bead depth, the diffusion path length, inches.',
    how: 'Diffusion scales inversely with it.',
    src: 'ASTM C1193 typical 1/4 in for small joints.',
  },
  // ---------------------------------------------------------------- room
  t_in: {
    what: 'Room dry-bulb temperature, °F, held constant.',
    how: 'Sets W_room together with RH, the warm end of the f-value chain, and the temperature of the room-side vent stream.',
    src: 'Default 70 °F. Fill time moves < 10 % over 65 to 75 °F.',
  },
  rh_in: {
    what: 'Room relative humidity, %, held constant.',
    how: 'W_room = 0.622·φ·p_ws(T_room)/(p − φ·p_ws). This is the wet stream in winter. Real rooms swing 20 to 30 % in winter and 50 to 60 % in summer; the model does not.',
    src: 'Default 35 %. Fill time ±5 to 14 % over 25 to 50 %; first-fog hour moves 10× (AUDIT §1 row 9).',
  },
  // ---------------------------------------------------------------- desiccant
  desiccant: {
    what: 'Desiccant type. Only 3A molecular sieve in the library today.',
    how: 'Selects the isotherm q_eq(RH,T) = q_max(T)·K(T)·RH/(1+K(T)·RH) and its temperature coefficients.',
    src: 'Constants fitted to published 3A vendor curves: q_max 0.21 kg/kg at 25 °C, K 60, −0.5 %/K, K halves per 23 K. ESTIMATE until a supplier sheet replaces them (AUDIT §3.5).',
  },
  grams: {
    what: 'Dry desiccant mass per window, grams.',
    how: 'Divided by glazing area to kg/m², multiplied by q_eq to get water capacity. Uptake per hour is the lesser of what the vents deliver and (q_eq − q)/τ.',
    src: 'Default 50 g. Capacity ≈ 0.21 × grams at 25 °C. Hours per gram is fill hours / grams.',
  },
  tau_h: {
    what: 'First-order time constant of the desiccant\'s approach to equilibrium, hours.',
    how: 'q(t+dt) = q_eq + (q − q_eq)·exp(−dt/τ). Encodes bead kinetics and cartridge air access together. Below ~1 h the sieve is supply-limited and τ stops mattering.',
    src: 'Default 2 h, an estimate. +80 to +107 % fill time at 8 h (AUDIT §1 row 5). Measurable with a scale and a humidity chamber.',
  },
  desorption: {
    what: 'Allow the desiccant to release water when its equilibrium loading drops below its actual loading (hot, dry cavity).',
    how: 'Same first-order law in reverse. Released water raises cavity W and leaves via the vents or condenses on the pane if colder than its dew point.',
    src: 'Default off (conservative). Nearly inert at hermetic leakage since released water has nowhere to go; −16 % condensation at moderate leakage (AUDIT §1 row 14).',
  },
  // ---------------------------------------------------------------- physics
  absorptance: {
    what: 'Solar absorptance of the existing pane, dimensionless.',
    how: 'T_cold += α·I_poa / h_out, with h_out the exterior film coefficient from wind speed. 0 disables the sun.',
    src: 'Default 0.10 (clear glass). 0 % effect on fill time; shifts first fog by hours (AUDIT §1 row 13).',
  },
  sky_radiation: {
    what: 'Clear-sky radiative cooling of the existing pane at night.',
    how: 'T_cold −= ε·σ·F·(T⁴ − T_sky⁴)/h_out with a cloud-cover correction from NSRDB cloud type.',
    src: 'Default on. 0 % on fill time; decides whether and when the pane fogs (first fog 264 h with, 5,830 h without, at gasketed leakage).',
  },
  pane_coupling: {
    what: 'Let vent air warm or cool the existing pane.',
    how: 'ΔT = [G_in_v(T_room − T) + G_out_v(T_out − T)] / (G_out + G_in + G_in_v + G_out_v), each G_v = 1/(1/(ṁ·c_p) + 1/h_cold). Upper bound.',
    src: 'Default on. 0 % on fill time; < 1 K on the pane at these leakages (ANLY-002 R2).',
  },
  max_years: {
    what: 'Cap on simulated years.',
    how: 'The TMY is replayed with state carried across the boundary until the sieve is full or this cap is reached. The run always finishes the year in which exhaustion falls.',
    src: 'Default 20. A run that hits the cap reports "> N years" and is flagged capped.',
  },
  // ---------------------------------------------------------------- outputs
  out_full: {
    what: 'Time until the desiccant is exhausted: first hour with loading q ≥ full_fraction × q_max(25 °C).',
    how: 'Default full_fraction 0.95. The sieve\'s equilibrium at 35 % room RH is 0.967 × q_max, so thresholds above ~0.96 never fire. Watch the "sieve holds air at" trace: protection fades as that RH rises, before this hour.',
    src: 'Engine: engine/lifetime.py run_lifetime. Cross-checked against an independent model within 2.5 % (AUDIT §2).',
  },
  out_fog: {
    what: 'First hour in which any water condenses on the existing pane\'s cavity face.',
    how: 'Condensation when the quasi-steady cavity humidity exceeds W_sat(T_cold). Depends on sky cooling and room RH far more than on the desiccant.',
    src: 'Model output; "none" means no condensing hour within the years run.',
  },
  out_hpg: {
    what: 'Hours of protection per gram of desiccant: fill hours / grams.',
    how: 'In the supply-limited regime this is ≈ 8760 / (annual water delivered per gram of capacity). The sub-line divides 8,760 by it to give grams for one year at this leakage.',
    src: 'Undefined when the run is not exhausted.',
  },
  out_source: {
    what: 'Net water each path delivered to the cavity over the sieve\'s life (to the hour it is full; the whole run if it never fills): outdoor air through the existing window, room air through the retrofit, and vapour diffusion through the sealant bead.',
    how: 'Each hour the solved cavity humidity W is compared with each path\'s own: N = ACH · m_air · (W_path − W) · dt. The split is exact because the supply is a flow-weighted mean. A negative value is a path that carried water OUT, which cold, dry outdoor air does in winter. Shares are shown only when every path is a source (a fresh sieve makes the cavity drier than anything around it); once any path is a remover the card shows adds and removes in grams instead. Windows longer than a year are shown per year.',
    src: 'engine/lifetime.py split_vent_net, contribution_shares; tests/test_contributions.py.',
  },
  out_pane: {
    what: 'Temperature of the existing pane\'s cavity-side face, °F.',
    how: 'T_out + f·(T_room − T_out) + sun − sky + vent warming.',
    src: 'engine/cavity.py.',
  },
  out_dew: {
    what: 'Dew point of the cavity air, °F, from its humidity ratio.',
    how: 'When this exceeds the pane temperature, the pane condenses. Floored at −40 for display (a fresh sieve drives it lower).',
    src: 'engine/psychro.py, Hyland-Wexler, ice branch below 0 °C.',
  },
  out_rh: {
    what: 'Relative humidity of the cavity air at the cavity air temperature.',
    how: 'The RH the desiccant sees; q_eq is evaluated at this RH and T_air.',
    src: 'Cavity air temperature is the film- and flow-weighted mean of the two surfaces and the vent stream.',
  },
  out_supply: {
    what: 'Humidity ratio of the mixed supply air, g water per kg dry air.',
    how: 'W_sup = (ACH_out·W_out + ACH_in·W_room) / (ACH_out + ACH_in). Water delivered per hour = (ACH_out + ACH_in) × m_cav × W_sup when the cavity is dry.',
    src: 'engine/lifetime.py build_tables.',
  },
  out_loading: {
    what: 'Desiccant loading as % of q_max(25 °C).',
    how: 'Rises by uptake / mass each hour; falls only with desorption on.',
    src: 'Full at full_fraction (default 95 %).',
  },
  out_rheq: {
    what: 'The RH the desiccant would hold still air at, given its current loading: the inverse isotherm RH_eq(q).',
    how: 'RH_eq = q / (K·(q_max − q)). Half full ≈ 1 %; 95 % full ≈ 15 to 30 %. This is the honest "protection left" gauge.',
    src: 'engine/desiccant.py rh_eq.',
  },
  out_uptake: {
    what: 'Water taken up by the desiccant this hour, milligrams per window.',
    how: 'Sum of the coupled substeps; equals supply-limited delivery when τ is short.',
    src: 'Water balance closes to rounding (test_properties::test_water_balance_on_the_desiccant).',
  },
  out_film: {
    what: 'Liquid film on the pane, micrometres (kg/m² × 1000).',
    how: 'Grows by condensation, shrinks by evaporation (instantaneous to saturation, upper bound), capped at 100 µm with the rest draining. Visible above 5 µm (assumption).',
    src: 'engine/moisture.py.',
  },
  out_vent: {
    what: 'Pane warming from vent air this hour, °F.',
    how: 'Two-stream conductance term; positive when room air dominates, negative when outdoor air does.',
    src: 'engine/cavity.py vent_cold_surface_rise_two_path.',
  },
  out_achout: {
    what: 'Outdoor-path air changes per hour this hour, including wind.',
    how: 'ACH = AL × 18.29 × ((dp + 0.5ρv²Cp)/75)^0.65 / offset.',
    src: 'engine/leakage.py.',
  },
  ach_derived: {
    what: 'Cavity air changes per hour derived from the rated leakage, operating pressure and offset (calm-wind value).',
    how: 'ACH = AL × 18.29 × (ΔP/75)^0.65 / offset. Compare: Eurac CFD open vent 23 to 78 ACH (60 mm cavity, summer).',
    src: 'engine/leakage.py ach_from_air_leakage.',
  },
}
