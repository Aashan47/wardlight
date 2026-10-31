// The brief 13 budget plan, computed in the browser from the sites collection the API serves (/api/city/{city}/sites,
// or the engine's recorded file). The same rule as agents/city13.py `plan` (the planner agent's rank_city_plan tool
// and GET /api/city/{city}/plan): walk the collection's rank order and fund each site whose capex fits in what is
// left; a site that does not fit is skipped and the walk goes on. Every figure is a site result the engine wrote or a
// sum of them; nothing is simulated here. `node scripts/check-plan-parity.mjs` compares the two against a running API.
import type { Sector, SiteProps } from './brief13'

export interface PlanSite extends SiteProps { lon: number; lat: number }
export interface PlanRow {
  order: number | null; rank: number; id: string; name: string; sector: Sector; archetype?: string; lga?: string
  capex_ngn: number; cumulative_ngn: number | null; pv_kwp: number | null; battery_kwh: number | null
  needed_h: number; today_h: number; with_h: number; gained_h: number; diesel_l_avoided: number
  roof_fit?: string; km_to_330kv?: number | null; facility_id?: string | null; funded: boolean; lon: number; lat: number
}
export interface Group {
  sites: number; funded: number; csh_needed: number; csh_today: number; csh_with_funded: number; csh_with_every_site: number
  share_today: number | null; share_with_funded: number | null; share_with_every_site: number | null
  diesel_l_avoided: number; capex_funded_ngn: number; capex_every_site_ngn: number; capex_to_fund_the_rest_ngn: number
}
export interface CityPlan {
  budget_ngn: number; days: number; sectors: Sector[]
  totals: Group & { spent_ngn: number; remaining_ngn: number; candidates: number; diesel_ngn_avoided: number | null }
  by_sector: Partial<Record<Sector, Group & { in_scope: boolean }>>
  rows: PlanRow[]; funded: PlanRow[]
  water: { m3_today: number; m3_with: number; people_with_upper: number }
}

const SPHERE_M3 = 0.015 // 15 L per person per day (Sphere 2018 minimum), the metrics file's people_served rule

function res(s: PlanSite, days: number) {
  const r = ((s.results ?? {}) as Record<string, { needed_h?: number | null; today_h?: number | null; with_h?: number | null; diesel_l_avoided?: unknown }>)[String(days)] ?? {}
  const dl = r.diesel_l_avoided
  return {
    needed: Number(r.needed_h ?? 0), today: Number(r.today_h ?? 0), withH: Number(r.with_h ?? 0),
    litres: typeof dl === 'number' ? dl : dl && typeof dl === 'object' && 'point' in dl ? Number((dl as { point: number }).point ?? 0) : 0,
  }
}

function group(xs: PlanSite[], funded: Set<string>, days: number): Group {
  let needed = 0, today = 0, withF = 0, withAll = 0, litres = 0, capF = 0, capAll = 0, nF = 0
  for (const s of xs) {
    const r = res(s, days), cap = Number(s.system?.capex_ngn ?? 0)
    needed += r.needed; today += r.today; withAll += r.withH; capAll += cap
    if (funded.has(s.id)) { nF++; withF += r.withH; litres += r.litres; capF += cap } else withF += r.today
  }
  const sh = (a: number) => (needed ? a / needed : null)
  return {
    sites: xs.length, funded: nF, csh_needed: needed, csh_today: today, csh_with_funded: withF, csh_with_every_site: withAll,
    share_today: sh(today), share_with_funded: sh(withF), share_with_every_site: sh(withAll), diesel_l_avoided: litres,
    capex_funded_ngn: capF, capex_every_site_ngn: capAll, capex_to_fund_the_rest_ngn: capAll - capF,
  }
}

export const ALL_SECTORS: Sector[] = ['health', 'water', 'cold']

export function planCity(sites: PlanSite[], budgetNgn: number, days: number, sectors: Sector[], dieselNgnPerL: number | null): CityPlan {
  const ranked = sites.filter((s) => s.rank != null).sort((a, b) => (a.rank! - b.rank!) || a.id.localeCompare(b.id))
  const secs = ALL_SECTORS.filter((x) => sectors.includes(x))
  const scope = ranked.filter((s) => secs.includes(s.sector))
  let spent = 0, order = 0
  const rows: PlanRow[] = []
  for (const s of scope) {
    const cap = Number(s.system?.capex_ngn ?? 0), r = res(s, days)
    const fund = spent + cap <= budgetNgn + 1e-6
    if (fund) { spent += cap; order++ }
    rows.push({
      order: fund ? order : null, rank: s.rank!, id: s.id, name: s.name, sector: s.sector, archetype: s.archetype, lga: s.lga,
      capex_ngn: cap, cumulative_ngn: fund ? spent : null, pv_kwp: s.system?.pv_kwp ?? null, battery_kwh: s.system?.battery_kwh ?? null,
      needed_h: r.needed, today_h: r.today, with_h: r.withH, gained_h: r.withH - r.today, diesel_l_avoided: r.litres,
      roof_fit: s.siting?.fit ?? s.siting?.roof_fit, km_to_330kv: s.siting?.km_to_330kv ?? null, facility_id: s.facility_id,
      funded: fund, lon: s.lon, lat: s.lat,
    })
  }
  const funded = rows.filter((r) => r.funded)
  const ids = new Set(funded.map((r) => r.id))
  const g = group(scope, ids, days)
  const by_sector: CityPlan['by_sector'] = {}
  for (const sec of ALL_SECTORS) {
    const xs = ranked.filter((s) => s.sector === sec)
    if (xs.length) by_sector[sec] = { ...group(xs, ids, days), in_scope: secs.includes(sec) }
  }
  let m3t = 0, m3w = 0
  for (const s of ranked) {
    if (s.sector !== 'water' || !s.m3_day) continue
    const r = res(s, days)
    if (r.needed <= 0) continue
    m3t += s.m3_day * r.today / r.needed
    m3w += s.m3_day * (ids.has(s.id) ? r.withH : r.today) / r.needed
  }
  return {
    budget_ngn: budgetNgn, days, sectors: secs,
    totals: { ...g, spent_ngn: spent, remaining_ngn: budgetNgn - spent, candidates: scope.length, diesel_ngn_avoided: dieselNgnPerL != null ? g.diesel_l_avoided * dieselNgnPerL : null },
    by_sector, rows, funded, water: { m3_today: m3t, m3_with: m3w, people_with_upper: m3w / SPHERE_M3 },
  }
}

export const PLAN_RULE = 'Plan order is the sites collection\'s rank: critical service-hours gained in a 60-day outage, most first; ties by lower capex. The budget funds each site in that order whose capex fits in what is left; a site that does not fit is skipped and the walk goes on.'

export function planCsv(p: CityPlan, cityName: string, dataVersion?: string): string {
  const cols = ['order', 'rank', 'id', 'name', 'sector', 'archetype', 'lga', 'funded', 'capex_ngn', 'cumulative_ngn', 'pv_kwp', 'battery_kwh', 'needed_h', 'today_h', 'with_h', 'gained_h', 'diesel_l_avoided', 'roof_fit', 'km_to_330kv', 'facility_id'] as const
  const q = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const head = [...cols, 'city', 'days', 'budget_ngn', 'sectors', 'data_version'].join(',')
  const body = p.rows.map((r) => [...cols.map((c) => (c === 'funded' ? (r.funded ? 'yes' : 'no') : r[c])), cityName, p.days, p.budget_ngn, p.sectors.join(' '), dataVersion ?? ''].map(q).join(','))
  return [head, ...body].join('\n')
}

export function download(name: string, text: string, type = 'text/csv') {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}
