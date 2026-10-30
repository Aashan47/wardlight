// Typed client. Live by default: the FastAPI at VITE_API_BASE (default "/api", same origin).
// VITE_FIXTURES=1 is the fallback flag: it reads the sample fixtures served at /fixtures/ instead.
import type {
  Brief, FacilityListItem, FacilityRecord, Feeder, Health, Plan, Results, SimulateRequest, SimulateResponse, Summary, Tier,
} from './types'

export const BASE: string = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '')
export const MODE: 'live' | 'fixture' = import.meta.env.VITE_FIXTURES === '1' ? 'fixture' : 'live'
/** Resolve a server path such as "/api/agent/runs/x/events" against the API's origin. */
export const apiUrl = (path: string) => (/^https?:/.test(BASE) ? new URL(path, BASE).href : path)

const cache = new Map<string, Promise<unknown>>()

async function get<T>(url: string): Promise<T> {
  const hit = cache.get(url)
  if (hit) return hit as Promise<T>
  const p = fetch(url, { headers: { Accept: 'application/json' } }).then(async (r) => {
    if (!r.ok) throw new ApiError(r.status, `${r.status} ${r.statusText}`)
    return (await r.json()) as T
  })
  cache.set(url, p)
  p.catch(() => cache.delete(url))
  return p
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

const fx = (path: string) => `/fixtures/${path}`

export const api = {
  health: () => get<Health>(MODE === 'live' ? `${BASE}/health` : fx('health.json')),
  summary: () => get<Summary>(MODE === 'live' ? `${BASE}/summary` : fx('summary.json')),

  async facilities(params: { state?: string; lga?: string; q?: string; tier?: Tier; limit?: number } = {}): Promise<FacilityListItem[]> {
    if (MODE === 'live') {
      const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v).map(([k, v]) => [k, String(v)]))
      return get<FacilityListItem[]>(`${BASE}/facilities?${qs}`)
    }
    const all = await get<FacilityListItem[]>(fx('facilities.json'))
    const q = params.q?.trim().toLowerCase()
    const out = all.filter((f) =>
      (!params.state || f.state === params.state) && (!params.lga || f.lga === params.lga) && (!params.tier || f.tier === params.tier) &&
      (!q || f.name.toLowerCase().includes(q) || f.id.toLowerCase().includes(q) || f.lga.toLowerCase().includes(q)))
    return params.limit ? out.slice(0, params.limit) : out
  },

  facility: (id: string) => get<FacilityRecord>(MODE === 'live' ? `${BASE}/facilities/${encodeURIComponent(id)}` : fx(`facility/${encodeURIComponent(id)}.json`)),

  async simulate(id: string, body: SimulateRequest): Promise<SimulateResponse> {
    if (MODE === 'live') {
      const r = await fetch(`${BASE}/facilities/${encodeURIComponent(id)}/simulate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      if (!r.ok) throw new ApiError(r.status, `${r.status} ${r.statusText}`)
      return r.json()
    }
    // Fixture: a precomputed grid of what-ifs; snap to the nearest point.
    type Cell = SimulateResponse & { trace_pqs_sdd: SimulateResponse['trace']; survival_pqs_sdd: SimulateResponse['survival']; fridge_days_pqs_sdd: SimulateResponse['fridge_days'] }
    const g = await get<{ pv_kwp: number[]; battery_kwh: number[]; results: Record<string, Cell> }>(fx(`simulate/${encodeURIComponent(id)}.json`))
    const near = (xs: number[], x: number) => xs.reduce((a, b) => (Math.abs(b - x) < Math.abs(a - x) ? b : a))
    const pv = near(g.pv_kwp, body.pv_kwp), bat = near(g.battery_kwh, body.battery_kwh)
    const c = g.results[`${pv}|${bat}`]
    const pqs = body.fridge_mode === 'pqs_sdd'
    return {
      pv_kwp: pv, battery_kwh: bat, cost_usd: c.cost_usd,
      survival: pqs ? c.survival_pqs_sdd : c.survival, fridge_days: pqs ? c.fridge_days_pqs_sdd : c.fridge_days,
      trace: pqs ? c.trace_pqs_sdd : c.trace, sample: true, snapped: pv !== body.pv_kwp || bat !== body.battery_kwh,
    }
  },

  /** Fixture grids, so sliders can step through exactly the points that exist. */
  simulateSteps: async (id: string): Promise<{ pv_kwp: number[]; battery_kwh: number[] } | null> => {
    if (MODE === 'live') return null
    const g = await get<{ pv_kwp: number[]; battery_kwh: number[] }>(fx(`simulate/${encodeURIComponent(id)}.json`))
    return { pv_kwp: g.pv_kwp, battery_kwh: g.battery_kwh }
  },

  plan: (params: { state?: string; budget_ngn?: number; target?: number } = {}) => {
    if (MODE === 'live') {
      const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))
      return get<Plan>(`${BASE}/plan?${qs}`)
    }
    return get<Plan>(fx('plan.json'))
  },

  feeder: (id: string) => get<Feeder>(MODE === 'live' ? `${BASE}/feeders/${encodeURIComponent(id)}` : fx(`feeder/${encodeURIComponent(id)}.json`)),
  results: () => get<Results>(MODE === 'live' ? `${BASE}/results` : fx('results.json')),

  brief: (p: { state: string; budget_ngn?: number; metric?: string }) => get<Brief>(`${BASE}/plan/brief?${new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))}`),
  briefCsvUrl: (p: { state: string; budget_ngn?: number; metric?: string }) => `${BASE}/plan/brief.csv?${new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))}`,

  /** The SMS route a feature phone uses (sandbox: the reply is returned, never sent). */
  async sms(text: string): Promise<{ reply: string; chars: number } | null> {
    if (MODE !== 'live') return null
    const r = await fetch(`${BASE}/sms/inbound`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ from: '+234000000000', to: 'sandbox', text, date: '', id: 'web', linkId: 'web' }) })
    if (!r.ok) throw new ApiError(r.status, `${r.status} ${r.statusText}`)
    return r.json()
  },

  recordings: () => MODE === 'live' ? get<{ recordings: { name: string; agent: string; label: string; what: string; question: string | null; facility_id: string | null }[] }>(`${BASE}/agent/recordings`) : Promise.resolve({ recordings: [] }),

  /** URLs a facility sheet needs offline (warmed into the service worker cache). */
  facilityUrls: (id: string) => MODE === 'live'
    ? [`${BASE}/facilities/${encodeURIComponent(id)}`]
    : [fx(`facility/${encodeURIComponent(id)}.json`), fx(`simulate/${encodeURIComponent(id)}.json`)],
}
