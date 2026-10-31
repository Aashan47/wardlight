import type { CityMetrics, EvidenceLabel, LabelValue, Num, Range, SiteProps, SiteResult, TodayWith } from '../api/brief13'

/** Read a figure the API sent as a number or as {point, lo, hi}. */
export function rv(x: Num): Range {
  if (x === null || x === undefined) return { point: null }
  if (typeof x === 'number') return { point: Number.isFinite(x) ? x : null }
  return { ...x, point: x.point ?? null, lo: x.lo ?? null, hi: x.hi ?? null }
}
export const pt = (x: Num) => rv(x).point
/** a figure the engine sends as {today, with}, or as one value meaning "with the plan" */
export function tw(x: Num | TodayWith | undefined): { today: Range | null; with: Range } {
  if (x && typeof x === 'object' && ('today' in x || 'with' in x)) {
    const o = x as TodayWith
    return { today: o.today === undefined ? null : rv(o.today), with: rv(o.with) }
  }
  return { today: null, with: rv(x as Num) }
}
export const has = (x: Num) => pt(x) !== null

/** a / b as a range: the numerator's interval over a fixed denominator. */
export function ratio(a: Num, b: Num): Range {
  const A = rv(a), B = pt(b)
  if (A.point === null || !B) return { point: null }
  return { point: A.point / B, lo: A.lo != null ? A.lo / B : null, hi: A.hi != null ? Math.min(1, A.hi / B) : null }
}

const nf = (d: number) => new Intl.NumberFormat('en-US', { maximumFractionDigits: d, minimumFractionDigits: 0 })
/** 1,284 / 12.9K / 4.2M / 1.3bn */
export function compact(n: number | null | undefined, d = 1): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return 'n/a'
  const a = Math.abs(n)
  if (a >= 1e9) return `${nf(d).format(n / 1e9)}bn`
  if (a >= 1e6) return `${nf(d).format(n / 1e6)}M`
  if (a >= 1e4) return `${nf(d).format(n / 1e3)}K`
  return nf(a < 10 ? 2 : 0).format(n)
}
export const full = (n: number | null | undefined) => (n === null || n === undefined || !Number.isFinite(n) ? 'n/a' : nf(0).format(Math.round(n)))
/** share as a percent, exactly the API's rule: one decimal, half up, a trailing .0 dropped (7%, 6.9%); a share below 1
    that would round to 100 is capped at 99.9. Exactly 1 prints as 100%. */
export function share(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return 'n/a'
  if (x >= 1) return '100%'
  let v = Math.floor(x * 1000 + 0.5 + 1e-9) / 10
  if (v >= 100) v = 99.9
  return `${Number.isInteger(v) ? v : v.toFixed(1)}%`
}
export const naira = (n: number | null | undefined) => (n === null || n === undefined ? 'n/a' : `N${compact(n)}`)
export const nairaKwh = (n: number | null | undefined) => (n === null || n === undefined ? 'n/a' : `N${full(n)}`)

/** "lo–hi" with an en dash, or null when the API sent no interval. */
export function span(r: Range, f: (n: number) => string): string | null {
  if (r.lo == null || r.hi == null) return null
  if (f(r.lo) === f(r.hi)) return null
  return `${f(r.lo)}–${f(r.hi)}`
}

// ---------------------------------------------------------------- evidence labels

const ORDER: EvidenceLabel[] = ['VERIFIED', 'ASSUMPTION', 'UNVERIFIED']
/** Read a label from a status word or from the engine's label sentence ("UNVERIFIED generator curve ..."). The
    weakest word in the sentence wins. DERIVED (arithmetic on verified figures) and VERIFIED_SECONDARY count as VERIFIED;
    PROPOSED, design standards and modelled supply count as ASSUMPTION. */
export function labelOf(v: LabelValue | undefined): EvidenceLabel | null {
  if (!v) return null
  const s = (typeof v === 'string' ? v : v.label ?? '').toUpperCase()
  if (/\bUNVERIFIED\b/.test(s)) return 'UNVERIFIED'
  if (/\bASSUMPTION\b|\bASSUMED\b|\bPROPOSED\b|DESIGN STANDARD|\bMODELLED\b|\bARCHETYPE\b|\bESTIMATE\b|PLACEHOLDER/.test(s)) return 'ASSUMPTION'
  if (/\bVERIFIED(_SECONDARY)?\b|^DERIVED\b|^SOURCED\b|^MEASURED\b/.test(s)) return 'VERIFIED'
  return null
}
export const labelNote = (v: LabelValue | undefined): string | null => {
  if (!v) return null
  if (typeof v === 'string') { const rest = v.replace(/^\s*(VERIFIED|ASSUMPTION|UNVERIFIED)\s*[:,.]\s*/i, ''); return rest || null }
  return v.note ?? null
}
/** The weakest label among the keys that exist (a headline is only as good as its weakest input). */
export function weakestLabel(labels: Record<string, LabelValue> | undefined, keys: string[]): EvidenceLabel | null {
  if (!labels) return null
  let worst = -1
  for (const k of keys) {
    for (const [lk, lv] of Object.entries(labels)) {
      if (lk === k || lk.startsWith(`${k}.`) || lk.startsWith(`${k}_`)) {
        const l = labelOf(lv)
        if (l) worst = Math.max(worst, ORDER.indexOf(l))
      }
    }
  }
  return worst < 0 ? null : ORDER[worst]
}
export function labelsFor(labels: Record<string, LabelValue> | undefined, keys: string[]): [string, LabelValue][] {
  if (!labels) return []
  return Object.entries(labels).filter(([lk]) => keys.some((k) => lk === k || lk.startsWith(`${k}.`) || lk.startsWith(`${k}_`)))
}

// ---------------------------------------------------------------- per-site results for one outage length

export function siteResult(p: SiteProps, days: number): SiteResult {
  const r = p.results
  let block: SiteResult | undefined
  if (r && typeof r === 'object') {
    const keyed = (r as Record<string, SiteResult>)[String(days)]
    block = keyed && typeof keyed === 'object' ? keyed : ('share_today' in r || 'today_h' in r || 'with_h' in r ? (r as SiteResult) : undefined)
  }
  const needed = block?.needed_h ?? null
  const shareToday = block?.share_today ?? (needed && block?.today_h != null ? block.today_h / needed : null) ?? p.share_today ?? null
  const shareWith = block?.share_with ?? (needed && block?.with_h != null ? block.with_h / needed : null) ?? p.share_with ?? null
  return { ...block, share_today: shareToday, share_with: shareWith }
}

export const SECTOR_NAME: Record<string, string> = { health: 'Health', water: 'Water pumping', cold: 'Cold chain and markets' }
export const SECTOR_SHORT: Record<string, string> = { health: 'Health', water: 'Water', cold: 'Cold chain' }
export const ROOF: Record<string, string> = { fits: 'Fits on its own roof', partial: 'Partly on the roof', ground: 'Ground-mounted inside the wall', unknown: 'Roof not known: no mapped buildings nearby' }
export const daysWords = (d: number) => (d === 60 ? 'two months' : `${d} days`)

/** Weakest label across the named labels and the statuses of the constants whose names start with the given prefixes. */
export function weakestOf(m: CityMetrics, labelKeys: string[], constPrefixes: string[] = []): EvidenceLabel | null {
  const xs: (EvidenceLabel | null)[] = [weakestLabel(m.labels, labelKeys)]
  for (const [n, c] of Object.entries(m.constants ?? {})) if (constPrefixes.some((p) => n.startsWith(p))) xs.push(labelOf(c.status))
  let worst = -1
  for (const l of xs) if (l) worst = Math.max(worst, ORDER.indexOf(l))
  return worst < 0 ? null : ORDER[worst]
}

/** which engine constants each label key rests on, so a row's chip reflects both */
export const CONSTS_FOR: Record<string, string[]> = {
  diesel: ['GEN', 'DIESEL_'], cost_diesel: ['GEN', 'DIESEL_'], diesel_price: ['DIESEL_'],
  cost_solar: ['COST_', 'BATTERY_', 'OM_', 'SYSTEM_', 'REPLACEMENT_', 'FX_'],
  gas_support: ['MEPP_SUPPORT', 'MEPP_AVG', 'MEPP_CAPACITY'], cost_gas_support: ['MEPP_SUPPORT', 'MEPP_AVG', 'MEPP_CAPACITY'], cost_breakeven: ['MEPP_SUPPORT', 'COST_'],
  gas_tariff: ['MEPP_COST', 'MEPP_NBET', 'FX_'], water: ['BH_', 'PUMP_', 'SOLAR_BH'], water_works: ['WATER_WORKS'],
  cold: ['COLD'], people_served: ['WATER_L'], roof: ['ROOF_', 'PV_KWP'],
}
export const rowLabel = (m: CityMetrics, keys: string[]) => weakestOf(m, keys, keys.flatMap((k) => CONSTS_FOR[k] ?? []))
