// Generates SAMPLE fixtures for the web app until the engine lands.
// Every number written here is synthetic (a toy model with a seeded random generator), except the
// fields marked "verified", which are copied from the verified-sources notes or the
// NERC row quoted in 06-PRODUCT-DESIGN.md. Every file carries "sample": true.
// Run: node scripts/make-fixtures.mjs
import { mkdirSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'data', 'fixtures', 'web')
rmSync(OUT, { recursive: true, force: true })
for (const d of ['', 'facility', 'simulate', 'feeder']) mkdirSync(join(OUT, d), { recursive: true })
const write = (p, obj) => writeFileSync(join(OUT, p), JSON.stringify(obj) + '\n')
const require_ = (p) => readFileSync(join(OUT, p), 'utf8')

// Seeded PRNG (mulberry32)
let seed = 20261029
const rnd = () => {
  seed |= 0; seed = (seed + 0x6d2b79f5) | 0
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296
}
const r2 = (x, d = 2) => Math.round(x * 10 ** d) / 10 ** d

// ---------- verified constants (quoted with source) ----------
const NGN_PER_USD = 1352.371 // CBN central rate 27 Oct 2026, SOURCES-VERIFIED section 5
const CO2_KG_PER_L = 2.697 // EPA 10.21 kg/gal derived, SOURCES-VERIFIED section 4
const BIRTH_RATE = 32.493 // per 1,000, World Bank 2024, SOURCES-VERIFIED section 2
const DOSES_PER_CHILD = 20 // DERIVED from the FHIR IG schedule, SOURCES-VERIFIED section 2

const SOURCES = [
  { name: 'NERC BEDC MYTO order, February 2026 (feeder bands and minimum hours)', url: 'https://nerc.gov.ng/wp-content/uploads/2026/04/BEDC_MYTO_FEB_2026.pdf', licence: 'Regulatory publication, licence not stated', retrieved: '2026-10-27' },
  { name: 'WHO PQS E003/RF05.3 and RF03-VP.2 (2 to 8 °C rule, holdover definition)', url: 'https://extranet.who.int/prequal/sites/default/files/document_files/PQS%20E03%20RF3-VP.2.pdf', licence: 'WHO document, no licence statement found', retrieved: '2026-10-27' },
  { name: 'SEforALL, Powering Healthcare: Nigeria technology roadmap', url: 'https://www.seforall.org/system/files/2022-06/Nigeria_technology_0.pdf', licence: 'Not stated in the PDF', retrieved: '2026-10-27' },
  { name: 'Energizing Health (WHO, World Bank, IRENA, SEforALL, 2023)', url: 'https://www.seforall.org/system/files/2023-01/energizing_health.pdf', licence: 'CC BY-NC-SA 3.0 IGO', retrieved: '2026-10-27' },
  { name: 'World Bank, crude birth rate, Nigeria (SP.DYN.CBRT.IN)', url: 'https://api.worldbank.org/v2/country/NGA/indicator/SP.DYN.CBRT.IN?format=json&per_page=20', licence: 'CC BY 4.0', retrieved: '2026-10-27' },
  { name: 'WorldPop Nigeria 2026, constrained, R2025A v1', url: 'https://hub.worldpop.org/geodata/summary?id=78608', licence: 'CC BY 4.0', retrieved: '2026-10-27' },
  { name: 'Gridfinder, predictive mapping of the global power system (Zenodo 3628142)', url: 'https://zenodo.org/records/3628142', licence: 'CC BY 4.0', retrieved: '2026-10-27' },
  { name: 'NASA POWER hourly API', url: 'https://power.larc.nasa.gov/docs/services/api/temporal/hourly/', licence: 'CC0 (NASA ESDS data policy), citation requested', retrieved: '2026-10-27' },
  { name: 'US EPA GHG Emission Factors Hub 2025 (diesel 10.21 kg CO2 per gallon)', url: 'https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf', licence: 'US government work', retrieved: '2026-10-27' },
  { name: 'Central Bank of Nigeria exchange rates', url: 'https://www.cbn.gov.ng/rates/ExchRateByCurrency.html', licence: 'Not stated', retrieved: '2026-10-27' },
  { name: 'GRID3 Nigeria Health Facilities v3.0 (HDX)', url: 'https://data.humdata.org/', licence: 'CC BY', retrieved: 'not yet loaded into the app' },
  { name: 'OpenFreeMap basemap (OpenMapTiles, OpenStreetMap contributors)', url: 'https://openfreemap.org', licence: 'ODbL data, OpenFreeMap terms', retrieved: 'used live, tiles not stored' },
]

// ---------- loads (wattages and hours from SEforALL Nigeria Type 2 PHC table, p. 10) ----------
// rooms: fridge, delivery, oxygen, lab, ward. Hours below say when each room needs power.
const ROOMS = [
  { key: 'fridge', name: 'Vaccine fridge', priority: 1, kw: 0.13, hours: 'all', source: 'SEforALL Nigeria technology PDF p. 10: refrigerator 130 W, 24 h' },
  { key: 'delivery', name: 'Delivery room', priority: 2, kw: 0.285, hours: 'night', source: 'SEforALL p. 10: procedure light 2 x 50 W, suction 185 W' },
  { key: 'oxygen', name: 'Oxygen concentrator', priority: 3, kw: 0.2, hours: 'night', source: 'SEforALL p. 10: oxygen concentrator 200 W' },
  { key: 'lab', name: 'Laboratory', priority: 4, kw: 0.14, hours: 'day', source: 'SEforALL p. 10: centrifuge 110 W, microscope 30 W' },
  { key: 'ward', name: 'Ward lights and fans', priority: 5, kw: 0.66, hours: 'night', source: 'SEforALL p. 10: interior lights 26 x 10 W; fans (sample share) 8 x 50 W' },
]
const RESERVE = { fridge: 0, delivery: 0.12, oxygen: 0.3, lab: 0.45, ward: 0.55 } // sample dispatch rule
const START = 18 // the night starts at 18:00
const HOURS = Array.from({ length: 24 }, (_, i) => (START + i) % 24)
const needs = (room, h) => room.hours === 'all' || (room.hours === 'night' ? (h >= 18 || h < 7) : (h >= 8 && h < 16))
const solarShape = (h) => { const x = (h + 0.5 - 6.5) / 12; return x <= 0 || x >= 1 ? 0 : Math.sin(Math.PI * x) ** 1.3 * 0.78 }

// a grid draw: promised hours as ceiling, a sample shortfall, blocks placed through the day
function gridDraw(minHours, offgrid) {
  if (offgrid) return HOURS.map(() => false)
  const hrs = Math.max(0, Math.round(minHours * (0.45 + 0.55 * rnd()) ))
  const on = new Array(24).fill(false)
  let left = hrs, guard = 0
  while (left > 0 && guard++ < 50) {
    const len = Math.min(left, 1 + Math.floor(rnd() * 5))
    const s = Math.floor(rnd() * 24)
    for (let k = 0; k < len; k++) if (!on[(s + k) % 24]) { on[(s + k) % 24] = true; left-- }
  }
  return on // indexed by position in HOURS
}

function simulate({ pv, bat, grid, mode = 'shared' }) {
  const trace = { start_hour: START, hour: HOURS, grid_on: [], solar_kw: [], load_kw: [], battery_soc: [], fridge_c: [], battery_kwh: bat, pv_kwp: pv, fridge_mode: mode, fridge_curve: 'illustrative', rooms: {} }
  for (const r of ROOMS) trace.rooms[r.key] = []
  let soc = bat > 0 ? 0.9 : 0, temp = 5.0, fridgeOk = true
  const served = Object.fromEntries(ROOMS.map((r) => [r.key, true]))
  HOURS.forEach((h, i) => {
    const g = grid[i]
    const solar = pv * solarShape(h)
    let energy = solar, load = 0
    for (const r of ROOMS) {
      const need = needs(r, h)
      let on = false
      if (need) {
        if (r.key === 'fridge' && mode === 'pqs_sdd') on = true // dedicated PQS array, not on the shared battery
        else if (r.key === 'fridge' && mode === 'icelined') on = g // mains ice-lined fridge: grid only
        else if (g) on = true
        else {
          const avail = energy + Math.max(0, soc - RESERVE[r.key]) * bat
          if (avail >= r.kw) { on = true; const fromSolar = Math.min(energy, r.kw); energy -= fromSolar; soc -= bat > 0 ? (r.kw - fromSolar) / bat : 0 }
        }
        if (on && !(r.key === 'fridge' && mode === 'pqs_sdd')) load += r.kw
        if (!on) served[r.key] = false
      }
      trace.rooms[r.key].push(need ? on : null)
    }
    if (g && bat > 0) soc = Math.min(1, soc + 1.5 / bat)
    if (energy > 0 && bat > 0) soc = Math.min(1, soc + energy / bat)
    soc = Math.max(0, soc)
    const fridgeOn = trace.rooms.fridge[i]
    temp = mode === 'pqs_sdd' ? 4.8 + 0.3 * Math.sin(i / 3) : fridgeOn ? Math.max(4.2, temp - 1.1) : temp + (mode === 'icelined' ? 0.22 : 0.55) // illustrative thermal curves (domestic 0.55, ice-lined 0.22 °C/h), not PQS figures
    if (temp > 8) fridgeOk = false
    trace.grid_on.push(g); trace.solar_kw.push(r2(solar)); trace.load_kw.push(r2(load)); trace.battery_soc.push(r2(soc, 3)); trace.fridge_c.push(r2(temp, 1))
  })
  return { trace, served, fridgeOk }
}

const wilson = (k, n) => { const z = 1.645, p = k / n, d = 1 + z * z / n; const c = (p + z * z / (2 * n)) / d; const m = (z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d; return { p: r2(p, 3), lo: r2(Math.max(0, c - m), 3), hi: r2(Math.min(1, c + m), 3) } }
// Every survival estimate for a facility uses the same seed and the same 120 modelled nights, so the
// headline, the per-load list, the what-if readout and the cost curve agree. The fridge "survives" a night
// when its interior stays inside 2 to 8 °C (brief 1's criterion), so its per-load figure IS the headline.
let FSEED = 1
function survival(pv, bat, minHours, offgrid, n = 120, mode = 'shared') {
  const keep = seed; seed = FSEED; const counts = Object.fromEntries(ROOMS.map((r) => [r.key, 0])); let fridgeDays = 0
  for (let k = 0; k < n; k++) { const s = simulate({ pv, bat, grid: gridDraw(minHours, offgrid), mode }); for (const r of ROOMS) if (s.served[r.key]) counts[r.key]++; if (s.fridgeOk) fridgeDays++ }
  seed = keep
  return { per_load: ROOMS.map((r) => ({ load: r.key, name: r.name, ...wilson(r.key === 'fridge' ? fridgeDays : counts[r.key], n) })), fridge_days: wilson(fridgeDays, n) }
}
// sample cost model (placeholders, not sourced prices)
const costUsd = (pv, bat) => Math.round(pv * 1000 * 1.1 + bat * 310 + (pv > 0 || bat > 0 ? 900 : 0))

// ---------- facilities ----------
const LGAS = [
  ['Oredo', 6.335, 5.627], ['Egor', 6.37, 5.58], ['Ikpoba-Okha', 6.3, 5.68], ['Ovia North-East', 6.6, 5.4], ['Ovia South-West', 6.47, 5.25],
  ['Uhunmwonde', 6.55, 5.88], ['Orhionmwon', 6.25, 6.0], ['Esan West', 6.74, 6.08], ['Esan Central', 6.72, 6.2], ['Esan North-East', 6.7, 6.33],
  ['Esan South-East', 6.62, 6.4], ['Etsako West', 7.07, 6.27], ['Etsako Central', 7.0, 6.45], ['Etsako East', 7.1, 6.55], ['Owan West', 7.1, 5.9],
  ['Owan East', 7.15, 6.05], ['Akoko-Edo', 7.3, 6.1], ['Igueben', 6.58, 6.23],
]
const TIERS = ['b_place', 'b_place', 'b_place', 'c_lga_mixture', 'c_lga_mixture', 'c_unit_mixture', 'c_unit_mixture', 'offgrid', 'offgrid', 'd_refused']
const BANDS = { A: 20, B: 16, C: 12, D: 8, E: 4 }
const REFUSAL_REASONS = ['No NERC row names this facility or its place, and its business unit is not known', 'Facility coordinates fall outside every DisCo business unit footprint in the sample']

const facilities = []
const hero = {
  id: 'WL-0001', name: 'New General Hospital', type: 'Hospital', level: 'Secondary', ownership: 'Public',
  state: 'Not yet matched to the registry', lga: 'Not yet matched to the registry', ward: null, lat: null, lon: null,
  tier: 'a_named', feeder_id: 'bedc-govt-house', band: 'C', grid_km: null, catchment: 15000, hero: true,
}
facilities.push(hero)
for (let i = 2; i <= 48; i++) {
  const [lga, la, lo] = LGAS[(i * 7) % LGAS.length]
  const tier = i === 2 ? 'b_place' : TIERS[Math.floor(rnd() * TIERS.length)]
  const band = tier === 'offgrid' || tier === 'd_refused' ? null : 'ABCDE'[1 + Math.floor(rnd() * 4)]
  facilities.push({
    id: `WL-${String(i).padStart(4, '0')}`, name: `Sample PHC ${String(i).padStart(2, '0')}, ${lga}`, type: 'Primary Health Center', level: 'Primary', ownership: 'Public',
    state: 'Edo', lga, ward: null, lat: r2(la + (rnd() - 0.5) * 0.22, 4), lon: r2(lo + (rnd() - 0.5) * 0.22, 4),
    tier, feeder_id: tier === 'b_place' ? `sample-feeder-${1 + (i % 4)}` : null, band, grid_km: tier === 'offgrid' ? r2(8 + rnd() * 30, 1) : r2(rnd() * 3, 1),
    catchment: Math.round((10000 + rnd() * 10000) / 100) * 100,
  })
}

const PV = [0, 2, 4, 6, 8]
const BAT = [0, 2, 5, 10, 20, 40]
const list = []
const ranked = []
const tierCounts = {}
for (const f of facilities) {
  tierCounts[f.tier] = (tierCounts[f.tier] ?? 0) + 1
  const refused = f.tier === 'd_refused'
  const offgrid = f.tier === 'offgrid'
  const mix = f.tier === 'c_unit_mixture' ? { C: 0.5, D: 0.3, E: 0.2 } : f.tier === 'c_lga_mixture' ? { B: 0.3, C: 0.5, D: 0.2 } : f.band ? { [f.band]: 1 } : {}
  const minHours = refused ? null : offgrid ? 0 : f.tier === 'c_unit_mixture' ? 12 * 0.5 + 8 * 0.3 + 4 * 0.2 : f.tier === 'c_lga_mixture' ? 16 * 0.3 + 12 * 0.5 + 8 * 0.2 : BANDS[f.band]
  const base = { id: f.id, name: f.name, type: f.type, lat: f.lat, lon: f.lon, state: f.state, lga: f.lga, tier: f.tier }
  if (refused) {
    list.push({ ...base, p_fridge_survives: null })
    write(`facility/${f.id}.json`, { sample: true, facility: f, match: { tier: 'd_refused', feeder_id: null, band: null, bands: {}, min_hours: null, evidence: null, reason: REFUSAL_REASONS[f.id.charCodeAt(6) % 2], promised_not_measured: true }, refused: true })
    continue
  }
  FSEED = 20261100 + Number(f.id.slice(3))
  const today = survival(0, 0, minHours, offgrid)
  // pick the cheapest grid point where the fridge survives with lo >= 0.9 (sample target)
  let best = null
  const grid = {}
  const keepSeed = seed
  seed = 108 + f.id.charCodeAt(6) * 31 + f.id.charCodeAt(7)
  const nightGrid = gridDraw(minHours, offgrid) // one modelled night, shared by every what-if so only the system changes
  seed = keepSeed
  for (const pv of PV) for (const bat of BAT) {
    const s = survival(pv, bat, minHours, offgrid)
    const sp = survival(pv, bat, minHours, offgrid, 120, 'pqs_sdd')
    const one = simulate({ pv, bat, grid: nightGrid })
    const two = simulate({ pv, bat, grid: nightGrid, mode: 'pqs_sdd' })
    grid[`${pv}|${bat}`] = { pv_kwp: pv, battery_kwh: bat, survival: s.per_load, fridge_days: s.fridge_days, cost_usd: costUsd(pv, bat), trace: one.trace, trace_pqs_sdd: two.trace, survival_pqs_sdd: sp.per_load, fridge_days_pqs_sdd: sp.fridge_days }
    const fr = s.per_load[0]
    if (fr.lo >= 0.9 && (!best || costUsd(pv, bat) < costUsd(best.pv, best.bat))) best = { pv, bat }
  }
  if (!best) best = { pv: 8, bat: 40 }
  const withSys = survival(best.pv, best.bat, minHours, offgrid)
  const iceToday = survival(0, 0, minHours, offgrid, 120, 'icelined')
  // sample rule: hospitals, and busy off-grid clinics (catchment over 15,000) with night deliveries, need the clinic system too
  const fix = f.hero || (offgrid && f.catchment > 15000) ? 'solar_clinic' : iceToday.fridge_days.lo >= 0.9 ? 'pqs_icelined' : 'pqs_sdd'
  const FIX_TEXT = {
    pqs_icelined: ['A PQS mains ice-lined fridge on the grid it has', 'With a PQS ice-lined fridge, this band already holds 2 to 8 °C on at least 90% of modelled days'],
    pqs_sdd: ['A PQS solar direct-drive fridge', offgrid ? 'No grid hours are modelled, so the fridge needs its own solar array' : 'Even a PQS ice-lined fridge leaves too many modelled days above 8 °C on this supply'],
    solar_clinic: ['A PQS solar direct-drive fridge plus the separate clinic system', f.hero ? 'A hospital with night loads beyond the cold chain: delivery, oxygen and wards need their own system' : 'Off-grid with a large catchment: night deliveries and oxygen need their own system beside the PQS fridge (sample rule)'],
  }
  const withFix = fix === 'pqs_icelined' ? iceToday : survival(0, 0, minHours, offgrid, 120, 'pqs_sdd')
  const fixCostUsd = fix === 'pqs_icelined' ? 860 : fix === 'pqs_sdd' ? 6900 : 6900 + costUsd(best.pv, best.bat) // ice-lined: Haier HBC-80 sheet price (USD 860, base 2021); SDD: sample placeholder
  // the hero night: a fixed draw so the video sample is stable
  const nightToday = simulate({ pv: 0, bat: 0, grid: nightGrid })
  const births = f.catchment * BIRTH_RATE / 1000
  const dosesYear = births * DOSES_PER_CHILD
  const capex = costUsd(best.pv, best.bat)
  const dieselL = Math.round(365 * (24 - (minHours ?? 0)) * 0.35 * 0.4) // sample: generator hours x sample litres per hour
  const monthlyDieselNgn = Math.round(dieselL / 12 * 1441.28) // NBS Oct 2024 price, labelled as such
  const monthlySystemNgn = Math.round(capex * NGN_PER_USD * (1 / 180 + 0.05 / 12))
  const curve = BAT.map((bat) => ({ battery_kwh: bat, pv_kwp: best.pv, cost_usd: costUsd(best.pv, bat), p_fridge: grid[`${best.pv}|${bat}`].survival[0] }))
  const rec = {
    fridge_system: { design: 'PQS solar direct drive vaccine fridge, dedicated array, no other loads', holdover_h_range: [83.7, 180], note: 'WHO PQS PV01.3 forbids other loads on a PQS solar fridge system' },
    clinic_system: { design: 'Shared clinic system for delivery room, oxygen, lab and ward', pv_kwp: best.pv, battery_kwh: best.bat },
    capex_usd: { lo: Math.round(capex * 0.85), mid: capex, hi: Math.round(capex * 1.2) },
    capex_ngn: { lo: Math.round(capex * 0.85 * NGN_PER_USD), mid: Math.round(capex * NGN_PER_USD), hi: Math.round(capex * 1.2 * NGN_PER_USD) },
    monthly_cost_ngn: monthlySystemNgn, monthly_diesel_ngn: monthlyDieselNgn,
    payback_months: monthlyDieselNgn > monthlySystemNgn ? Math.round(capex * NGN_PER_USD / monthlyDieselNgn) : null,
    diesel_l_avoided: dieselL, co2_kg_avoided: Math.round(dieselL * CO2_KG_PER_L),
    who_pays: ['State Primary Health Care Board', 'Rural Electrification Agency programme', 'Donor grant', 'Lease-to-own (option)'],
    maintains: 'Local installer under an annual service contract (sample assumption)',
  }
  const record = {
    sample: true,
    facility: f,
    match: f.hero ? {
      tier: 'a_named', feeder_id: 'bedc-govt-house', feeder_name: 'GOVT. HOUSE', disco: 'BEDC', band: 'C', bands: { C: 1 }, min_hours: 12, promised_not_measured: true,
      evidence: { file: 'BEDC_MYTO_FEB_2026.pdf', url: 'https://nerc.gov.ng/wp-content/uploads/2026/04/BEDC_MYTO_FEB_2026.pdf', page: 14, sn: 108, row_text: 'Band C | GOVT. HOUSE | HIGH COURT, NEW GENERAL HOSPITAL, GRA, NWAWOLOR | 12', crop: null, verified: true },
      reason: 'The facility is named in the feeder\'s street list',
    } : {
      tier: f.tier, feeder_id: f.feeder_id, feeder_name: f.feeder_id ? f.feeder_id.replace('sample-feeder-', 'SAMPLE FEEDER ') : null, disco: 'BEDC', band: f.tier.startsWith('c_') ? null : f.band, bands: mix, min_hours: minHours, promised_not_measured: true,
      evidence: f.tier === 'offgrid' ? null : { file: null, url: null, page: null, sn: null, row_text: null, crop: null, verified: false },
      reason: f.tier === 'b_place' ? 'Its town or ward is named in a feeder row (sample)' : f.tier === 'c_lga_mixture' ? 'Only its LGA is matched to feeder rows, so its supply is a mixture of those feeders\' bands (sample)' : f.tier === 'c_unit_mixture' ? 'Only its DisCo business unit is known, so its supply is a mixture of that unit\'s bands (sample)' : `Modelled with no grid hours: ${f.grid_km} km from the nearest predicted grid line (sample)`,
    },
    supply_model: { label: 'modelled', promised_hours: minHours, median_hours: minHours === null ? null : r2(minHours * 0.72, 1), p10_hours: minHours === null ? null : r2(minHours * 0.45, 1), p90_hours: minHours, note: 'Promised hours are the ceiling; actual supply is modelled below them. Sample values.' },
    loads: ROOMS.map(({ key, name, priority, kw, hours, source }) => ({ key, name, priority, kw, hours, source })),
    survival_today: today.per_load,
    survival_with_system: withSys.per_load,
    brief_metric: {
      uptime_today: today.fridge_days, uptime_with_system: withFix.fridge_days,
      doses_year: Math.round(dosesYear),
      doses_protected_today: Math.round(dosesYear * today.fridge_days.p), doses_protected_with_system: Math.round(dosesYear * withFix.fridge_days.p),
      doses_note: `Estimate: catchment ${f.catchment.toLocaleString('en-US')} (sample) x crude birth rate 32.493 per 1,000 (World Bank 2024) x 20 doses per child in year one (FHIR IG schedule, unofficial)`,
    },
    recommended: rec,
    cost_curve: curve,
    trace: nightToday.trace,
    fix: { category: fix, label: FIX_TEXT[fix][0], reason: FIX_TEXT[fix][1], cost_ngn: Math.round(fixCostUsd * NGN_PER_USD), cost_note: fix === 'pqs_icelined' ? 'Haier HBC-80 PQS sheet price, USD 860 (base 2021), converted at the CBN rate' : 'Sample placeholder cost' },
    scenarios: [
      { key: 'domestic', label: 'Household fridge (headline)', headline: true, uptime: today.fridge_days, note: 'Today\'s equipment is unknown; a household fridge is the headline assumption' },
      { key: 'pqs_icelined', label: 'PQS ice-lined fridge', headline: false, uptime: iceToday.fridge_days, note: 'If the clinic already has a PQS mains ice-lined fridge' },
    ],
  }
  write(`facility/${f.id}.json`, record)
  write(`simulate/${f.id}.json`, { sample: true, pv_kwp: PV, battery_kwh: BAT, results: grid })
  list.push({ ...base, p_fridge_survives: today.fridge_days.p })
  if (f.lat !== null) ranked.push({
    id: f.id, name: f.name, lga: f.lga, lat: f.lat, lon: f.lon, tier: f.tier,
    cost_ngn: Math.round(fixCostUsd * NGN_PER_USD), fridge_nights_saved: Math.round(365 * (withFix.fridge_days.p - today.fridge_days.p)),
    unmet_hours: r2(24 - (minHours ?? 0), 1),
    uptime_today: today.fridge_days.p, uptime_with_system: withFix.fridge_days.p,
    doses_protected_gain: Math.round(dosesYear * (withFix.fridge_days.p - today.fridge_days.p)),
    fix,
  })
}
for (const r of ranked) r.score = r2(r.doses_protected_gain / (r.cost_ngn / 1e6), 2) // doses protected per N1m of the cold-chain fix
ranked.sort((a, b) => b.score - a.score)
let cum = 0
ranked.forEach((r, i) => {
  cum += r.cost_ngn; r.rank = i + 1; r.cumulative_ngn = cum
  const FIXN = { pqs_icelined: 'Fix (i), PQS ice-lined fridge', pqs_sdd: 'Fix (ii), PQS solar fridge', solar_clinic: 'Fix (iii), solar fridge and clinic system' }
  r.reason = `${FIXN[r.fix]}. ` + (r.tier === 'offgrid' ? 'Off-grid: no grid hours modelled (sample)' : `Band ${facilities.find((f) => f.id === r.id).band ?? 'mixture'} promise leaves ${r.unmet_hours} h a day uncovered (sample)`)
})
write('plan.json', { sample: true, state: 'Edo', target: 0.99, budget_ngn_max: cum, currency_note: 'Converted at N1,352.37 per USD, CBN central rate, 27 Oct 2026', ranked })
write('facilities.json', list)

// feeders: one verified row; sample feeders carry no NERC text
write('feeder/bedc-govt-house.json', {
  sample: false, id: 'bedc-govt-house', name: 'GOVT. HOUSE', disco: 'BEDC', band: 'C', min_hours: 12,
  band_history: [{ order_file: 'BEDC_MYTO_FEB_2026.pdf', order_month: '2026-02', band: 'C', min_hours: 12 }],
  history_note: 'Only the February 2026 order has been read for this feeder so far.',
  rows: [{ file: 'BEDC_MYTO_FEB_2026.pdf', url: 'https://nerc.gov.ng/wp-content/uploads/2026/04/BEDC_MYTO_FEB_2026.pdf', page: 14, sn: 108, band: 'C', feeder_name: 'GOVT. HOUSE', location: 'HIGH COURT, NEW GENERAL HOSPITAL, GRA, NWAWOLOR', min_hours: 12, verified: true }],
  facilities: [{ id: 'WL-0001', name: 'New General Hospital', tier: 'a_named', how: 'Named in the street list of row 108' }],
})
for (let k = 1; k <= 4; k++) {
  const id = `sample-feeder-${k}`
  write(`feeder/${id}.json`, {
    sample: true, id, name: `SAMPLE FEEDER ${k}`, disco: 'BEDC', band: null, min_hours: null, band_history: [], history_note: 'Sample feeder: no NERC row is attached in sample data.', rows: [],
    facilities: facilities.filter((f) => f.feeder_id === id).map((f) => ({ id: f.id, name: f.name, tier: f.tier, how: 'Town or ward named in a feeder row (sample)' })),
  })
}

const refusals = {}
facilities.filter((f) => f.tier === 'd_refused').forEach((f) => { const r = REFUSAL_REASONS[f.id.charCodeAt(6) % 2]; refusals[r] = (refusals[r] ?? 0) + 1 })
write('summary.json', {
  sample: true,
  by_state: [{ state: 'Edo', total: facilities.length - 1, tiers: Object.fromEntries(Object.entries(tierCounts).map(([k, v]) => [k, k === 'a_named' ? v - 1 : v])) }, { state: 'Not yet matched to the registry', total: 1, tiers: { a_named: 1 } }],
  tiers: tierCounts,
  refusals: Object.entries(refusals).map(([reason, count]) => ({ reason, count })),
  headline: { facilities: facilities.length, matched: facilities.length - (tierCounts.d_refused ?? 0), refused: tierCounts.d_refused ?? 0 },
  quotes: [
    { text: 'The acceptable temperature range for storing vaccine is +2°C to +8°C.', source: 'WHO PQS E003/RF03-VP.2, p. 2', url: 'https://extranet.who.int/prequal/sites/default/files/document_files/PQS%20E03%20RF3-VP.2.pdf' },
    { text: '6 - 10 hours Average power supply from any combination of sources', source: 'SEforALL, Nigeria data insights, p. 3 (partly 2008 data)', url: 'https://www.seforall.org/system/files/2022-06/Nigeria_data_insights_0.pdf' },
    { text: 'No additional loads, such as lighting or pumping, are to be connected to the solar power system.', source: 'WHO PQS E003/PV01.3, p. 4', url: 'https://extranet.who.int/prequal/sites/default/files/document_files/WHO%20PQS%20E003-PV01_3_20151116.pdf' },
  ],
})
write('health.json', { ok: true, fixture: true, sample: true, data_version: 'sample', sources: SOURCES })
write('results.json', {
  sample: false,
  prereg_url: 'docs/PREREG.md',
  rows: [
    { id: 'T1', what: 'Reading NERC feeder appendices', target: 'at least 97% of 200 spot-checked rows correct', result: null, status: 'not_run' },
    { id: 'T2', what: 'Facility to feeder matching, tiers (a) and (b)', target: 'at least 90% of 100 sampled matches correct', result: null, status: 'not_run' },
    { id: 'T3', what: 'Supply model calibration', target: 'measured hours of failing Band A feeders inside the 90% interval for at least 85%', result: null, status: 'not_run' },
    { id: 'T4', what: 'Solar resource', target: 'NASA POWER annual PV yield within 10% of PVGIS at 20 sites', result: null, status: 'not_run' },
    { id: 'T5', what: 'Sizing sanity', target: 'a typical PHC sizes inside SEforALL\'s 5 to 10 kWp, 36 to 72 kWh, or the difference is explained', result: null, status: 'not_run' },
    { id: 'T6', what: 'Speed', target: 'what-if simulation under 1 s at the 95th percentile', result: null, status: 'not_run' },
    { id: 'T7', what: 'Brief metric reported with every input sourced', target: 'no target: no measured uptime exists to compare against', result: null, status: 'not_run' },
  ],
})
console.log(`wrote ${facilities.length} facilities to ${OUT}`)

// ---------- agent sessions (SAMPLE replays until agent F records real ones) ----------
// Event schema: 11-AGENTS-DESIGN.md, "The agent experience on screen". Reasoning events carry a placeholder,
// never invented model text. Every number in an answer is listed in its grounding check with the tool it came from.
const PLACEHOLDER = '[Sample replay: no model was called. In a recorded session the model\'s own stated reasoning appears here, verbatim.]'
function session(kind, question, steps, body) {
  const ev = []; let t = 0
  const push = (type, data, gap = 380) => { t += gap; ev.push({ t, type, data }) }
  push('plan', { steps }, 200)
  body(push)
  const sums = Object.fromEntries(ev.filter((e) => e.type === 'tool_result').map((e) => [e.data.id, e.data.summary]))
  for (const e of ev.filter((x) => x.type === 'check')) for (const n of e.data.numbers_checked) {
    const esc = n.text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    if (!new RegExp(`(^|[^0-9.,])${esc}([^0-9]|$)`).test(sums[n.tool] ?? '')) throw new Error(`${kind}: "${n.text}" not found in ${n.tool}: ${sums[n.tool]}`)
  }
  push('done', { model: 'none (sample replay)', tokens: 0, cost_usd: 0, recorded: true, sample: true, duration_ms: t + 300 })
  write(`agent-${kind}.json`, { sample: true, label: 'recorded sample', kind, question, events: ev })
}
const fmtN = (x) => `N${(x / 1e6).toFixed(1)}m`
// planner
{
  const BUDGET = 50e6
  const funded = ranked.filter((r) => r.cumulative_ngn <= BUDGET)
  const spent = funded.reduce((a, r) => a + r.cost_ngn, 0)
  const doses = funded.reduce((a, r) => a + r.doses_protected_gain, 0)
  const byFix = { pqs_icelined: 0, pqs_sdd: 0, solar_clinic: 0 }; funded.forEach((r) => byFix[r.fix]++)
  const nextUp = ranked.find((r) => r.cumulative_ngn > BUDGET)
  const refusedN = facilities.filter((f) => f.tier === 'd_refused').length
  const unfunded = ranked.length - funded.length
  const wf = JSON.parse(JSON.stringify(nextUp))
  session('planner', 'I have N50 million for Edo this year. Protect the most vaccine doses.', [
    { id: 's1', title: 'Read Edo facilities, their tiers and recommended fixes' },
    { id: 's2', title: 'Rank by doses protected per naira under N50m' },
    { id: 's3', title: 'Test the first facility the budget misses' },
    { id: 's4', title: 'Check the evidence behind the picks' },
    { id: 's5', title: 'Check every number, then write the plan' },
  ], (push) => {
    push('step_start', { id: 's1' })
    push('reasoning', { text: PLACEHOLDER, source: 'sample' }, 250)
    push('tool_call', { id: 't1', name: 'facilities.list', args: { state: 'Edo' } })
    push('tool_result', { id: 't1', summary: `${facilities.length} facilities read: ${ranked.length} with a location, ${refusedN} refused`, rows: facilities.length, ms: null, data: { considering: ranked.map((r) => r.id) } }, 700)
    push('step_start', { id: 's2' })
    push('tool_call', { id: 't2', name: 'plan.rank', args: { state: 'Edo', budget_ngn: BUDGET, target: 0.99, metric: 'doses_per_naira' } })
    push('tool_result', { id: 't2', summary: `${funded.length} facilities fit for ${fmtN(spent)}: ${byFix.pqs_icelined} ice-lined, ${byFix.pqs_sdd} solar fridge, ${byFix.solar_clinic} solar plus clinic; +${doses.toLocaleString('en-US')} doses protected a year; ${unfunded} located facilities past the budget`, rows: ranked.length, ms: null, data: { funded: funded.map((r) => r.id), budget_ngn: BUDGET } }, 900)
    push('step_start', { id: 's3' })
    push('tool_call', { id: 't3', name: 'facility.what_if', args: { id: wf.id, fix: wf.fix } })
    push('tool_result', { id: 't3', summary: `${wf.name}: ${fmtN(wf.cost_ngn)} would take the total past the budget; fridge would hold ${Math.round(wf.uptime_with_system * 100)}% of days`, rows: 1, ms: null, data: { considering: [wf.id] } }, 800)
    push('step_start', { id: 's4' })
    push('tool_call', { id: 't4', name: 'evidence.get', args: { ids: funded.slice(0, 3).map((r) => r.id).concat(['WL-0001']) } })
    push('tool_result', { id: 't4', summary: 'Sample facilities carry no NERC row text; New General Hospital has a real NERC row but no registry location, so it is not ranked', rows: 4, ms: null }, 700)
    push('citation', { facility_id: 'WL-0001', file: 'BEDC_MYTO_FEB_2026.pdf', page: 14, sn: 108, row_text: 'Band C | GOVT. HOUSE | HIGH COURT, NEW GENERAL HOSPITAL, GRA, NWAWOLOR | 12' }, 300)
    push('step_start', { id: 's5' })
    const nums = [
      { text: String(funded.length), tool: 't2' }, { text: fmtN(spent), tool: 't2' }, { text: doses.toLocaleString('en-US'), tool: 't2' },
      { text: String(byFix.pqs_icelined), tool: 't2' }, { text: String(byFix.pqs_sdd), tool: 't2' }, { text: String(byFix.solar_clinic), tool: 't2' },
      { text: String(unfunded), tool: 't2' }, { text: String(refusedN), tool: 't1' }, { text: fmtN(wf.cost_ngn), tool: 't3' },
    ]
    push('check', { kind: 'grounding', numbers_checked: nums, unmatched: [] }, 500)
    push('answer', {
      markdown: `**Fund ${funded.length} facilities for ${fmtN(spent)}.** They protect about ${doses.toLocaleString('en-US')} more doses a year.\n\n- ${byFix.pqs_icelined} need only a PQS ice-lined fridge on the grid they have\n- ${byFix.pqs_sdd} need a PQS solar fridge\n- ${byFix.solar_clinic} need a solar fridge plus the clinic system\n\nFirst in line: [[${funded[0].id}]], [[${funded[1].id}]], [[${funded[2].id}]].`,
      funded: funded.map((r) => r.id),
      not_reached: [
        { text: `${unfunded} located facilities are past the budget; next is [[${wf.id}]] at ${fmtN(wf.cost_ngn)}` },
        { text: `${refusedN} facilities are refused: no feeder evidence` },
        { text: 'New General Hospital [[WL-0001]] has a real NERC row but no registry location yet' },
      ],
      totals: { facilities: funded.length, spent_ngn: spent, doses_protected: doses },
    }, 400)
  })
}
// verifier (sandbox, simulated replies)
{
  const d = JSON.parse(require_('facility/WL-0001.json'))
  const [dom, ice] = d.scenarios
  const before = { p: r2((dom.uptime.p + ice.uptime.p) / 2, 3), lo: dom.uptime.lo, hi: ice.uptime.hi }
  FSEED = 777
  const keep = seed
  // after the hours reply: nights conditioned on 8 to 10 grid hours, household fridge, 400 draws
  let ok = 0; const n = 400
  for (let k = 0; k < n; k++) {
    const on = new Array(24).fill(false); let left = 8 + Math.floor(rnd() * 3), guard = 0
    while (left > 0 && guard++ < 60) { const len = Math.min(left, 1 + Math.floor(rnd() * 5)), st = Math.floor(rnd() * 24); for (let j = 0; j < len; j++) if (!on[(st + j) % 24]) { on[(st + j) % 24] = true; left-- } }
    if (simulate({ pv: 0, bat: 0, grid: on }).fridgeOk) ok++
  }
  seed = keep
  const after = wilson(ok, n)
  const pc = (x) => `${Math.round(x * 100)}%`
  session('verifier', 'Verify New General Hospital by SMS', [
    { id: 'v1', title: 'Ask which fridge holds the vaccines' },
    { id: 'v2', title: 'Ask for yesterday\'s grid hours' },
    { id: 'v3', title: 'Re-run the night with the answers' },
    { id: 'v4', title: 'Check every number, then report' },
  ], (push) => {
    push('tool_call', { id: 'u0', name: 'facility.get', args: { id: 'WL-0001' } })
    push('tool_result', { id: 'u0', summary: `Fridge type unknown: ${pc(before.lo)} to ${pc(before.hi)} of days at 2 to 8 °C across scenarios`, rows: 1, ms: null, data: { interval: before, stage: 'before' } }, 600)
    push('step_start', { id: 'v1' })
    push('reasoning', { text: PLACEHOLDER, source: 'sample' }, 250)
    push('tool_call', { id: 'u1', name: 'sms.send', args: { to: 'officer in charge (sandbox)', text: 'Wardlight: what fridge holds your vaccines? Reply 1 ice-lined, 2 solar, 3 household, 4 none' } })
    push('tool_result', { id: 'u1', summary: 'Reply: "3" (household fridge)', rows: 1, ms: null, data: { sms_reply: '3', interval: dom.uptime, stage: 'fridge known' } }, 1400)
    push('step_start', { id: 'v2' })
    push('tool_call', { id: 'u2', name: 'sms.send', args: { to: 'officer in charge (sandbox)', text: 'How many hours of grid power did you have yesterday? Reply a number' } })
    push('tool_result', { id: 'u2', summary: 'Reply: "9"', rows: 1, ms: null, data: { sms_reply: '9' } }, 1400)
    push('step_start', { id: 'v3' })
    push('tool_call', { id: 'u3', name: 'facility.simulate', args: { id: 'WL-0001', fridge: 'household', grid_hours: '8 to 10', draws: n } })
    push('tool_result', { id: 'u3', summary: `Household fridge, 8 to 10 grid hours: ${pc(after.p)} of days (${pc(after.lo)} to ${pc(after.hi)})`, rows: n, ms: null, data: { interval: after, stage: 'hours known' } }, 800)
    push('step_start', { id: 'v4' })
    push('check', { kind: 'grounding', numbers_checked: [{ text: pc(before.lo), tool: 'u0' }, { text: pc(before.hi), tool: 'u0' }, { text: pc(after.p), tool: 'u3' }, { text: pc(after.lo), tool: 'u3' }, { text: pc(after.hi), tool: 'u3' }], unmatched: [] }, 500)
    push('answer', { markdown: `**The interval narrowed from ${pc(before.lo)} to ${pc(before.hi)} down to ${pc(after.lo)} to ${pc(after.hi)}.** The clinic reports a household fridge, so the headline scenario applies: its vaccines hold 2 to 8 °C on about ${pc(after.p)} of days. Fix: [[WL-0001]] needs ${d.fix.label.charAt(0).toLowerCase() + d.fix.label.slice(1)}.`, funded: [], not_reached: [], totals: {} }, 400)
  })
}
// regulator watcher (sample feeders, so the diff is labelled sample)
{
  const feeders = [2, 3].map((k) => ({ id: `sample-feeder-${k}`, name: `SAMPLE FEEDER ${k}`, ids: facilities.filter((f) => f.feeder_id === `sample-feeder-${k}`).map((f) => f.id) }))
  const changes = [
    { feeder_id: feeders[0].id, name: feeders[0].name, from: 'B', to: 'C', from_hours: 16, to_hours: 12, facilities: feeders[0].ids },
    { feeder_id: feeders[1].id, name: feeders[1].name, from: 'C', to: 'D', from_hours: 12, to_hours: 8, facilities: feeders[1].ids },
  ]
  const affected = changes.reduce((a, c) => a + c.facilities.length, 0)
  session('watcher', 'A new BEDC order is out. What changed?', [
    { id: 'w1', title: 'Fetch the new order' }, { id: 'w2', title: 'Read the feeder appendix' },
    { id: 'w3', title: 'Diff bands against the previous order' }, { id: 'w4', title: 'Re-run the affected facilities' }, { id: 'w5', title: 'Check every number, then write the change log' },
  ], (push) => {
    push('step_start', { id: 'w1' })
    push('tool_call', { id: 'x1', name: 'nerc.fetch_order', args: { disco: 'BEDC', order: 'sample' } })
    push('tool_result', { id: 'x1', summary: 'Sample order loaded (no real order fetched in sample mode)', rows: 1, ms: null }, 600)
    push('step_start', { id: 'w2' })
    push('reasoning', { text: PLACEHOLDER, source: 'sample' }, 250)
    push('tool_call', { id: 'x2', name: 'nerc.read', args: { file: 'sample', pages: 'appendix' } })
    push('tool_result', { id: 'x2', summary: '4 sample feeder rows read', rows: 4, ms: null }, 700)
    push('step_start', { id: 'w3' })
    push('tool_call', { id: 'x3', name: 'bands.diff', args: { disco: 'BEDC', against: 'previous order' } })
    push('tool_result', { id: 'x3', summary: `${changes.length} feeders changed band: ${changes.map((c) => `${c.name} ${c.from} (${c.from_hours} h) to ${c.to} (${c.to_hours} h)`).join('; ')}`, rows: changes.length, ms: null, data: { changes } }, 700)
    push('step_start', { id: 'w4' })
    push('tool_call', { id: 'x4', name: 'facilities.rerun', args: { feeders: changes.map((c) => c.feeder_id) } })
    push('tool_result', { id: 'x4', summary: `${affected} facilities re-run`, rows: affected, ms: null }, 800)
    push('step_start', { id: 'w5' })
    push('check', { kind: 'grounding', numbers_checked: [{ text: String(changes.length), tool: 'x3' }, { text: '16', tool: 'x3' }, { text: '12', tool: 'x3' }, { text: '8', tool: 'x3' }, { text: String(affected), tool: 'x4' }], unmatched: [] }, 500)
    push('answer', { markdown: `**${changes.length} feeders moved down a band.** ${changes[0].name} went from Band B (16 h) to Band C (12 h); ${changes[1].name} from Band C (12 h) to Band D (8 h). ${affected} facilities were re-run.`, funded: [], not_reached: [], totals: { facilities: affected } }, 400)
  })
}
