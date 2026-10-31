// ============================================================================================================
// MOCK DATA. NOT RESULTS. Layout placeholders for the brief 13 screens until the engine stream serves
// /api/city/... and drops fixtures in data/fixtures/brief13/. Every number below is synthetic, from a seeded
// generator; every name says "Mock"; every position is a schematic scatter around a city centre. The client
// (brief13-client.ts) uses this only in `npm run dev` or with VITE_BRIEF13_MOCK=1, and every screen that shows
// it carries a MOCK badge. A production build never falls back to it.
// ============================================================================================================
import type {
  CityId, CityMetrics, CorridorFC, CorridorFeature, OwnershipRow, Sector, SiteProps, SitesFC, Siting,
} from './brief13'

const CENTRE: Record<CityId, [number, number]> = { maiduguri: [13.157, 11.846], damaturu: [11.961, 11.747], yola: [12.47, 9.21] }
const N_SITES: Record<CityId, number> = { maiduguri: 64, damaturu: 26, yola: 34 }

function rng(seed: number) {
  let s = seed >>> 0
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 2 ** 32 }
}
const seedOf = (s: string) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7)

const MOCK_OWNERSHIP: OwnershipRow[] = [
  { sector: 'health', owns: 'Mock owner', pays: 'Mock payer', guards: 'Mock guard', repairs: 'Mock repairer', model: 'Mock model text', label: 'ASSUMPTION' },
  { sector: 'water', owns: 'Mock owner', pays: 'Mock payer', guards: 'Mock guard', repairs: 'Mock repairer', model: 'Mock model text', label: 'ASSUMPTION' },
  { sector: 'cold', owns: 'Mock owner', pays: 'Mock payer', guards: 'Mock guard', repairs: 'Mock repairer', model: 'Mock model text', label: 'UNVERIFIED' },
]

export function mockSites(city: CityId): SitesFC {
  const r = rng(seedOf(city))
  const [lon0, lat0] = CENTRE[city]
  const sectors: Sector[] = ['health', 'water', 'cold']
  const features = Array.from({ length: N_SITES[city] }, (_, i) => {
    const sector = sectors[i % 7 < 4 ? 0 : i % 7 < 6 ? 1 : 2]
    const a = r() * Math.PI * 2, d = Math.sqrt(r()) * 0.07
    const kw = Math.round((sector === 'cold' ? 6 + r() * 10 : sector === 'water' ? 3 + r() * 12 : 1 + r() * 14) * 10) / 10
    const today = Math.round(r() * 0.35 * 100) / 100
    const planned = r() > 0.12
    const withShare = planned ? Math.round((0.82 + r() * 0.18) * 100) / 100 : today
    const p: SiteProps = {
      id: `mock-${city}-${String(i + 1).padStart(3, '0')}`, name: `Mock ${sector} site ${i + 1}`, sector,
      archetype: `mock ${sector} archetype`, kw, rank: planned ? i + 1 : null, planned,
      share_today: today, share_with: withShare,
      siting: { roof_fit: r() > 0.3 ? 'fits' : r() > 0.5 ? 'partial' : 'ground', pv_kwp: Math.round(kw * 2.2 * 10) / 10, battery_kwh: Math.round(kw * 9), corridor_km: Math.round(r() * 30) / 10, new_line_km: 0 },
    }
    return { type: 'Feature' as const, id: p.id, properties: p, geometry: { type: 'Point' as const, coordinates: [lon0 + Math.cos(a) * d, lat0 + Math.sin(a) * d * 0.9] } }
  })
  return { type: 'FeatureCollection', features, city, mock: true }
}

export function mockMetrics(city: CityId, days: number): CityMetrics {
  const sites = mockSites(city).features.map((f) => f.properties)
  const r = rng(seedOf(city) + days)
  const per = (s: Sector | null) => {
    const xs = sites.filter((x) => !s || x.sector === s)
    const need = xs.reduce((a, x) => a + (x.kw ?? 0) * 24 * days, 0)
    const today = xs.reduce((a, x) => a + (x.kw ?? 0) * 24 * days * (x.share_today ?? 0), 0)
    const withH = xs.reduce((a, x) => a + (x.kw ?? 0) * 24 * days * (x.share_with ?? 0), 0)
    return { sites: xs.length, csh_needed: Math.round(need), csh_today: Math.round(today), csh_today_diesel: Math.round(today + (need - today) * 0.6), csh_with: { point: Math.round(withH), lo: Math.round(withH * 0.95), hi: Math.round(Math.min(need, withH * 1.03)) } }
  }
  const all = per(null)
  const litres = Math.round(all.csh_needed * 0.11)
  const fits = sites.filter((s) => s.siting?.roof_fit === 'fits').length
  const partial = sites.filter((s) => s.siting?.roof_fit === 'partial').length
  return {
    city, days, mock: true, data_version: 'mock',
    impact: {
      ...all, by_sector: { health: per('health'), water: per('water'), cold: per('cold') },
      diesel_l_avoided: { point: litres, lo: Math.round(litres * 0.8), hi: Math.round(litres * 1.2) },
      diesel_ngn_avoided: { point: litres * 3000, lo: litres * 2400, hi: litres * 3600 },
      water_m3_per_day_kept: { point: Math.round(1000 + r() * 900), lo: 800, hi: 2200 }, people_served: { point: Math.round(50000 + r() * 20000), lo: 40000, hi: 80000 },
      cold_rooms_kept: sites.filter((s) => s.sector === 'cold' && s.planned).length,
    },
    innovation: { local_share: { point: 0.9, lo: 0.85, hi: 0.94 }, sites: sites.filter((s) => s.planned).length, new_line_km: 0, corridor: { km_330: 700, towers: 2700 }, community_owned_sites: sites.filter((s) => s.sector === 'cold').length },
    sustainability: {
      cost_per_kwh_ngn: { solar: { point: 300, lo: 240, hi: 380 }, diesel: { point: 1200, lo: 1000, hi: 1500 }, gas_support: { point: 150, lo: 60, hi: 300 } },
      gas_output_mwh_per_month: { lo: 7000, hi: 30000 }, gas_support_ngn_per_month: 2e9,
      gas_breakeven_mwh_per_month: { point: 7000 },
      co2_t_avoided: { point: Math.round(litres * 0.0027), lo: Math.round(litres * 0.0022), hi: Math.round(litres * 0.0032) },
      ownership: MOCK_OWNERSHIP,
      funding: [{ source: 'Mock funder', covers: 'Mock line', label: 'ASSUMPTION' }, { source: 'Mock funder 2', covers: 'Mock line', label: 'UNVERIFIED' }],
    },
    feasibility: { roof_fit: { fits, partial, ground: sites.length - fits - partial }, sites: sites.length, new_line_km: 0, median_corridor_km: 1.4, serviceable_locally: ['Mock part'] },
    scalability: { plan_minutes: { point: 4 }, checklist: ['Mock checklist item one', 'Mock checklist item two', 'Mock checklist item three'] },
    labels: { csh: 'ASSUMPTION', diesel_l_per_kwh: 'UNVERIFIED', diesel_price: 'VERIFIED', local_share: 'ASSUMPTION', corridor: 'VERIFIED', cost_solar: 'ASSUMPTION', cost_diesel: 'UNVERIFIED', gas_support: 'VERIFIED', gas_output: 'ASSUMPTION', roof_fit: 'ASSUMPTION', scalability: 'ASSUMPTION' },
    sources: [{ name: 'Mock source', url: '#', licence: 'n/a', retrieved: 'n/a' }],
  }
}

export function mockCorridor(): CorridorFC {
  // schematic: a bent polyline between three city centres, not the mapped route
  const path: [number, number][] = [[11.17, 10.29], [11.5, 10.9], [11.961, 11.747], [12.5, 11.8], [13.0, 11.83], [13.12, 11.84]]
  const towers: CorridorFeature[] = []
  for (let i = 0; i < path.length - 1; i++) for (let k = 0; k < 8; k++) {
    const t = k / 8
    towers.push({ type: 'Feature', properties: { kind: 'tower', name: 'Mock tower' }, geometry: { type: 'Point', coordinates: [path[i][0] + (path[i + 1][0] - path[i][0]) * t, path[i][1] + (path[i + 1][1] - path[i][1]) * t] } })
  }
  return {
    type: 'FeatureCollection', mock: true,
    features: [
      { type: 'Feature', properties: { kind: 'line', voltage_kv: 330, name: 'Mock 330 kV line' }, geometry: { type: 'LineString', coordinates: path } },
      ...towers,
      { type: 'Feature', properties: { kind: 'substation', name: 'Mock substation' }, geometry: { type: 'Point', coordinates: [13.12, 11.84] } },
      { type: 'Feature', properties: { kind: 'plant', plant_source: 'gas', name: 'Mock gas plant (MEPP position placeholder)' }, geometry: { type: 'Point', coordinates: [13.2, 11.88] } },
      { type: 'Feature', properties: { kind: 'plant', plant_source: 'solar', name: 'Mock UNIMAID/UMTH solar (position placeholder)', part_of_plan: false }, geometry: { type: 'Point', coordinates: [13.09, 11.81] } },
    ],
  }
}

export function mockSiting(id: string): Siting {
  const city = (id.split('-')[1] as CityId) ?? 'maiduguri'
  const f = mockSites(city).features.find((x) => x.properties.id === id)?.properties
  const kw = f?.kw ?? 5
  return {
    id, name: f?.name ?? 'Mock site', sector: f?.sector ?? 'health', archetype: f?.archetype, city, mock: true,
    pv_kwp_needed: { point: f?.siting?.pv_kwp ?? 10 }, roof_kwp_available: { point: Math.round(kw * 3) }, roof_area_m2: { point: Math.round(kw * 18) }, buildings: 3,
    roof_fit: f?.siting?.roof_fit ?? 'fits', battery_kwh: { point: f?.siting?.battery_kwh ?? 40 }, battery_room: 'Mock room description',
    new_line_km: 0, corridor_km: { point: f?.siting?.corridor_km ?? 1 },
    anti_theft: [{ measure: 'Mock measure one', label: 'ASSUMPTION' }, { measure: 'Mock measure two', label: 'UNVERIFIED' }, 'Mock measure three'],
    ownership: MOCK_OWNERSHIP.find((o) => o.sector === f?.sector),
    labels: { roof_fit: 'ASSUMPTION' },
  }
}
