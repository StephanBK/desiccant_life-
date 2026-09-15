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
    how: 'As width. Also the chimney height of each layer\'s single-sided loop: ΔP_loop = |ρ_side − ρ_cavity|·g·k·H, so a taller window breathes more through the same cracks.',
    src: 'Default 96 in. At 8 K and k = 0.75 the loop pressure over 8 ft is about 0.7 Pa (engine/pressure.py).',
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
    how: 'Converted to a flow coefficient C = AL × 18.29 / 75^0.65 (m³/h per m² per Pa^0.65). The two layers are in SERIES: one signed pressure difference room-to-outdoor per hour, the same air passes both, the tighter layer takes most of the pressure and sets the flow. Outdoor air enters only in hours when outdoor pressure is the higher one (wind, or stack below the neutral plane in winter).',
    src: 'Published anchors: AERC baseline single-pane 2.0; new fixed commercial spec 0.06 (ticked). Values between are estimates. Even with a hermetic retrofit this layer breathes outdoor air through its own cracks (single-sided loop), so it matters on its own (AUDIT §6).',
  },
  wind_scaling: {
    what: 'Legacy toggle. Only used when leakage is given as bare ACH (the parallel model); with rated leakage the wind enters the signed pressure model as 0.5·ρ·v²·Cp by direction.',
    how: 'Legacy path: ΔP_out(h) = dp_pa + 0.5·ρ·v(h)²·0.6.',
    src: 'Kept for older API calls.',
  },
  al_in: {
    what: 'Rated air leakage of the RETROFIT (the secondary window), cfm/ft² at 75 Pa.',
    how: 'Same coefficient. In series with the existing window; room air enters only in hours when room pressure is the higher one (HVAC pressurisation, stack above the neutral plane in winter, leeward suction outside). Plus its own single-sided loop with the room. The tighter of the two layers sets the through-flow; each layer\'s own leakage sets its loop.',
    src: 'AERC best certified insert 0.06 (Alpen WinSert, Dec 2021, ticked). Wet-sealed 0.005 is the ASTM E283 detection floor, not a measurement; Hermetic 0.0 is the IGU-grade other end of the same unknown. Weeks at the floor, years at hermetic: a cavity pressure-decay test on an installed unit is what settles it.',
  },
  dp_pa: {
    what: 'Reference pressure for the derived ACH shown under each ladder only. The solver no longer runs at a fixed pressure.',
    how: 'ACH shown = AL × 18.29 × (ΔP/75)^0.65 / offset at this ΔP, for that layer alone. The run uses the signed hourly pressure from HVAC, stack and wind (Building group).',
    src: 'Legacy input, default 3 Pa.',
  },
  p_occ_pa: {
    what: 'HVAC pressurisation of the room relative to outdoors during occupied hours, Pa. Positive pushes room air through the retrofit into the cavity.',
    how: 'Added to stack and wind each occupied hour to form the signed ΔP. Flow through the two layers in series scales as |ΔP|^0.65; the fed side follows the sign.',
    src: 'Default +5 Pa: the low end of the 5 to 25 Pa design range (ideal setpoint 12.5 Pa), matching field measurements in existing buildings, which run at 1 to 2 Pa and cannot hold a high setpoint through a leaky old facade. ESTIMATE; a BAS trend of building static settles it for a given building.',
  },
  p_unocc_pa: {
    what: 'HVAC pressurisation during unoccupied hours, Pa.',
    how: 'As above for hours outside the occupied window.',
    src: 'Default 0 Pa: night setback closes the outdoor damper, so only stack and wind act. Set negative if exhaust runs with intake closed.',
  },
  occ_start_h: {
    what: 'First occupied hour of the day (0 to 24).',
    how: 'Occupied when start ≤ hour < end. Wrap past midnight is allowed (start > end).',
    src: 'Default 07:00.',
  },
  occ_end_h: {
    what: 'First unoccupied hour of the day (0 to 24, exclusive).',
    how: 'See occupied start.',
    src: 'Default 19:00.',
  },
  weekdays_only: {
    what: 'Apply the occupied pressure on weekdays only.',
    how: 'A TMY has no real calendar (each month is spliced from a different year), so a synthetic calendar starting on a Monday is used. The share of occupied hours (36 % with the defaults) is what matters, not the dates.',
    src: 'Default on.',
  },
  floors: {
    what: 'Number of storeys in the building.',
    how: 'The neutral pressure plane is taken at mid-height (uniform leakage). Height above it = (window floor − 0.5 − floors/2) × floor height. Stack ΔP = (ρ_out − ρ_in)·g·h: positive (room pushes out) above the plane in winter, negative below, reversed in summer.',
    src: 'Default 10. A ground-floor window in a 20-storey building at 0 °C outside sees about −8 Pa; the 5th of 10 about zero. Real neutral planes shift with shaft and lobby leakage; this is an estimate.',
  },
  window_floor: {
    what: 'Floor the window is on (1 = ground).',
    how: 'See floors. The window sits at the middle of its floor.',
    src: 'Default 5.',
  },
  floor_height_ft: {
    what: 'Floor-to-floor height, ft.',
    how: 'See floors.',
    src: 'Default 11.8 ft (3.6 m), typical commercial.',
  },
  series_model: {
    what: 'Use the series pressure model (default). Off = legacy parallel model: both layers at the same fixed operating pressure, both feeding the cavity every hour.',
    how: 'The legacy model overstates airflow by 3× (equal layers) to 60× (retrofit 60× tighter than the existing window) and credits the leaky side with the moisture. Kept only for comparison.',
    src: 'AUDIT §7.',
  },
  loops: {
    what: 'Single-sided loop through each layer\'s own cracks. A small chimney: the cavity air is warmer or colder than the side beyond the layer, so air leaves through the layer\'s high crack and comes in through its low crack, nothing passing the other layer.',
    how: 'ΔP_loop = |ρ_side − ρ_cavity|·g·k·H_window; flow of half the layer\'s leakage at ΔP_loop/2. Added to the through-flow. This is why a hermetic retrofit over an unsealed old window still breathes outdoor air at a few ACH, and why both seals matter.',
    src: 'Ideal-gas buoyancy; the crack placement (k) and the sub-1 Pa exponent are the assumptions. Gust pumping and the wind gradient over the face are not modelled (second order).',
  },
  loop_k: {
    what: 'Where the cracks are: the fraction of the window height between the average inlet and the average outlet of the loop.',
    how: 'k = 1: all leakage at head and sill, the strongest chimney (an operable sash; a perimeter wet seal that fails at the corners). k = 0.5: leakage spread evenly over the height, half the pull. k = 0: all cracks at one height, no chimney whatever the rating.',
    src: 'Default 0.75, ESTIMATE between spread-out and all-at-the-ends. Loop flow scales as k^0.65, so 0.5 vs 1.0 is a 1.6× difference.',
  },
  loop_n: {
    what: 'Flow exponent used for the loop, which runs well below 1 Pa.',
    how: 'q ∝ ΔP^n. At 75 Pa cracks are turbulent-ish (0.65); at 0.3 Pa they are probably laminar (1.0), which would give up to 6× less loop flow from the same rating.',
    src: 'Default 0.65, the conservative choice for desiccant life. Set 1.0 to see the laminar case.',
  },
  breathing: {
    what: 'Thermal breathing: the cavity air contracts as it cools and draws in air from both sides in proportion to their leakage.',
    how: 'ACH_breath(h) = max(0, T_air(h−1) − T_air(h)) / T_air(h). About 0.003 ACH for a 1 K hourly drop; the only two-sided exchange in the model and the floor when both layers are hermetic.',
    src: 'Ideal gas; no assumption beyond that. Gust pumping (ΔP/P_atm ≈ 1e-4 per gust) is not modelled and only matters below ~0.01 ACH.',
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
    how: 'Each hour the solved cavity humidity W is compared with each path\'s own: N = ACH · m_air · (W_path − W) · dt. The split is exact because the supply is a flow-weighted mean. A negative value is a path that carried water OUT, which cold, dry outdoor air does in winter. Shares are shown only when every path is a source (a fresh sieve makes the cavity drier than anything around it); once any path is a remover the card shows adds and removes in grams instead. Windows longer than a year are shown per year, with the life total against capacity in the reading line.',
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
    how: 'W_sup = (ACH_out·W_out + ACH_in·W_room) / (ACH_out + ACH_in), where each ACH is that hour\'s real inflow from its side (through-flow on the high-pressure side, plus that layer\'s loop and breathing share). Water delivered per hour = (ACH_out + ACH_in) × m_cav × W_sup when the cavity is dry.',
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
    what: 'Outdoor air entering the cavity this hour, air changes per hour.',
    how: 'Through-flow when the signed pressure is negative (outdoors higher: wind, or stack below the neutral plane in winter), plus the single-sided loop through the existing window, plus the outdoor share of breathing.',
    src: 'engine/pressure.py hour_flow.',
  },
  out_achin: {
    what: 'Room air entering the cavity this hour, air changes per hour.',
    how: 'Through-flow when the signed pressure is positive (HVAC pressurisation, stack above the neutral plane in winter, leeward suction outside), plus the single-sided loop through the retrofit, plus the room share of breathing. Never both through-flows in the same hour.',
    src: 'engine/pressure.py hour_flow.',
  },
  out_dp: {
    what: 'Signed pressure difference this hour, room minus outdoors, Pa.',
    how: 'HVAC schedule + stack from the floor position + wind by direction against the facade. Positive feeds room air through the retrofit; negative feeds outdoor air through the existing window; the size sets the through-flow as |ΔP|^0.65 across both layers in series.',
    src: 'engine/pressure.py.',
  },
  ach_derived: {
    what: 'Air changes this layer ALONE would give at the reference pressure. Not what the run uses: the run solves both layers in series at the signed hourly pressure, so the through-flow is at most the tighter layer\'s value here.',
    how: 'ACH = AL × 18.29 × (ΔP/75)^0.65 / offset. Compare: Eurac CFD open vent 23 to 78 ACH (60 mm cavity, summer).',
    src: 'engine/leakage.py ach_from_air_leakage.',
  },
}
