import type { CorridorFC, CorridorFeature, Sector } from '../api/brief13'

export interface MapSite { id: string; name: string; sector: Sector; kw: number; lon: number; lat: number; glow: number; planned: boolean; rank: number | null; today: number | null; withPlan: number | null }
export type Bounds = [[number, number], [number, number]]

export const SECTOR_COLOR: Record<Sector, string> = { health: '#4F8BEA', water: '#2AA592', cold: '#A94BC8' } // validated: dataviz six checks, dark surface
export const LAMP = '#F6C453'
export const DARK_SITE = '#2A3342'

export const kindOf = (f: CorridorFeature) => String(f.properties?.kind ?? f.properties?.power ?? '').toLowerCase()
export const kvOf = (f: CorridorFeature): number | null => {
  const p = f.properties ?? {}
  if (typeof p.voltage_kv === 'number') return p.voltage_kv
  const v = Number(String(p.voltage ?? '').split(';')[0])
  return Number.isFinite(v) && v > 0 ? (v > 1000 ? v / 1000 : v) : null
}
/** transmission lines only: OSM maps substations as closed ways too */
export const isLine = (f: CorridorFeature) => {
  const k = kindOf(f)
  if (/substation|plant|tower|pole/.test(k)) return false
  return /line|cable/.test(k) || ((f.geometry.type === 'LineString' || f.geometry.type === 'MultiLineString') && !k)
}
/** MEPP (OSM names it "Maiduguri Emeregency Power Plant", source oil), the UNIMAID solar plant and its battery plant */
export function plantKind(f: CorridorFeature): 'gas' | 'solar' | 'battery' | null {
  if (!/plant|generator/.test(kindOf(f))) return null
  const p = (f.properties ?? {}) as Record<string, unknown>
  const s = `${p.plant_source ?? ''} ${p['plant:source'] ?? ''} ${p.source ?? ''} ${p.name ?? ''}`.toLowerCase()
  if (/solar|photovoltaic/.test(s)) return 'solar'
  if (/battery/.test(s)) return 'battery'
  if (/\bgas\b|mepp|maiduguri eme\w*ency/.test(s)) return 'gas'
  return null
}
/** one point for any geometry (centroid of a polygon ring, first point of a line) */
export function anchor(f: CorridorFeature): [number, number] | null {
  const g = f.geometry
  if (g.type === 'Point') return g.coordinates as [number, number]
  if (g.type === 'Polygon' || g.type === 'LineString') {
    const r = (g.type === 'Polygon' ? g.coordinates[0] : g.coordinates) as number[][]; if (!r?.length) return null
    const s = r.reduce((a, c) => [a[0] + c[0], a[1] + c[1]], [0, 0])
    return [s[0] / r.length, s[1] / r.length]
  }
  return null
}

export function boundsOfCoords(cs: [number, number][], pad = 0.02): Bounds | null {
  if (!cs.length) return null
  let w = 180, s = 90, e = -180, n = -90
  for (const [x, y] of cs) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y) }
  return [[w - pad, s - pad], [e + pad, n + pad]]
}
export function lineCoords(c: CorridorFC | null): [number, number][] {
  if (!c) return []
  const out: [number, number][] = []
  for (const f of c.features) {
    if (!isLine(f)) continue
    if (f.geometry.type === 'LineString') out.push(...(f.geometry.coordinates as [number, number][]))
    if (f.geometry.type === 'MultiLineString') for (const l of f.geometry.coordinates) out.push(...(l as [number, number][]))
  }
  return out
}

/** frame the dense city, not its outliers: 4th to 96th percentile of the site positions, padded */
export function cityFrame(cs: [number, number][], pad = 0.015): Bounds | null {
  if (cs.length < 8) return boundsOfCoords(cs, pad)
  const q = (xs: number[], f: number) => { const s = [...xs].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.max(0, Math.round(f * (s.length - 1))))] }
  const xs = cs.map((c) => c[0]), ys = cs.map((c) => c[1])
  return [[q(xs, 0.04) - pad, q(ys, 0.04) - pad], [q(xs, 0.96) + pad, q(ys, 0.96) + pad]]
}
