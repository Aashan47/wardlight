// Brief 13 data: live API first, then the engine's recorded fixtures (data/fixtures/brief13, served at
// /fixtures/brief13/), then, in development or with VITE_BRIEF13_MOCK=1 only, the typed mock. Each answer says
// where it came from, and the screens mark anything that is not live.
import { BASE, MODE } from './client'
import type { CityId, CityMetrics, CorridorFC, DataSource, Siting, SiteTrace, SitesFC, Sourced } from './brief13'
import { mockCorridor, mockMetrics, mockSiting, mockSites } from './brief13-mock'
import { normMetrics, normSites, normSiting } from './brief13-normalize'
import { CITIES } from './brief13'

export const MOCK_ALLOWED: boolean = import.meta.env.DEV || import.meta.env.VITE_BRIEF13_MOCK === '1'
const FX = '/fixtures/brief13'

export class NotAvailable extends Error {
  constructor(what: string) { super(`${what} is not available from the API yet`) }
}

const cache = new Map<string, Promise<Sourced<unknown>>>()

async function json<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: 'application/json, application/geo+json' } })
  if (!r.ok) throw new Error(`${r.status}`)
  const ct = r.headers.get('content-type') ?? ''
  if (!/json/.test(ct)) throw new Error('not json') // a dev server answers a missing file with index.html
  return (await r.json()) as T
}

function resolve<T>(key: string, live: string, fixtures: (string | (() => Promise<T>))[], mock: () => T, what: string, norm: (x: T) => T = (x) => x): Promise<Sourced<T>> {
  const hit = cache.get(key)
  if (hit) return hit as Promise<Sourced<T>>
  const p = (async (): Promise<Sourced<T>> => {
    if (MODE === 'live') {
      try { return { data: norm(await json<T>(`${BASE}${live}`)), src: 'live' } } catch { /* fall through */ }
    }
    for (const f of fixtures) {
      try { return { data: norm(typeof f === 'string' ? await json<T>(`${FX}/${f}`) : await f()), src: 'fixture' } } catch { /* next */ }
    }
    if (MOCK_ALLOWED) return { data: mock(), src: 'mock' }
    throw new NotAvailable(what)
  })()
  cache.set(key, p)
  p.catch(() => cache.delete(key))
  return p
}

export const b13 = {
  metrics: (city: CityId, days: number) => resolve<CityMetrics>(
    `m:${city}:${days}`, `/city/${city}/metrics?days=${days}`,
    [`metrics-${city}-${days}.json`, `city/${city}/metrics_${days}.json`],
    () => mockMetrics(city, days), 'The city metrics', normMetrics),

  sites: (city: CityId) => resolve<SitesFC>(
    `s:${city}`, `/city/${city}/sites`,
    [`sites-${city}.geojson`, `city/${city}/sites.geojson`],
    () => mockSites(city), 'The site list', normSites),

  corridor: () => resolve<CorridorFC>(
    'corridor', '/corridor', ['corridor.geojson', 'corridor.json'], () => mockCorridor(), 'The transmission corridor'),

  siting: (id: string) => resolve<Siting>(
    `siting:${id}`, `/sites/${encodeURIComponent(id)}/siting`,
    // the engine ships one file per city, keyed by site id
    CITIES.map((c) => async () => { const all = await sitingFile(c.id); if (!all[id]) throw new Error('not here'); return all[id] }),
    () => mockSiting(id), 'The siting card', normSiting),

  /** the site's simulated outage, hourly; live engine first (about a second, then cached), then a recorded file */
  trace: (id: string, days: number) => resolve<SiteTrace>(
    `trace:${id}:${days}`, `/sites/${encodeURIComponent(id)}/outage_trace?days=${days}`,
    [`trace-${id}-${days}.json`],
    () => { throw new NotAvailable('The outage trace for this site') }, 'The outage trace for this site'),
}

const sitingFiles = new Map<string, Promise<Record<string, Siting>>>()
function sitingFile(city: string) {
  let p = sitingFiles.get(city)
  if (!p) { p = json<Record<string, Siting>>(`${FX}/siting-${city}.json`); sitingFiles.set(city, p); p.catch(() => sitingFiles.delete(city)) }
  return p
}

/** Strongest claim we may make about a set of sources: live beats fixture beats mock. */
export const weakest = (xs: (DataSource | undefined)[]): DataSource | undefined =>
  xs.includes('mock') ? 'mock' : xs.includes('fixture') ? 'fixture' : xs.every((x) => x === 'live') ? 'live' : undefined
