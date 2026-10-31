// The engine's payloads, read into the contract shapes the screens use. Only renames and lifts: no figure is made up.
// Engine field (left) -> contract field (right) where they differ:
//   metrics.name -> city_name; labels.constants -> constants; labels.<object> dropped from labels
//   labels[k] + label_status[k] -> labels[k] = {label: status, note: sentence} (status is read from label_status, never
//   from the sentence's words); sustainability.cost_labels + cost_label_status -> labels.cost_<k>
//   sources[{text, url, status}] -> Source {name: text, url, status}
//   feasibility.km_to_330kv_median -> median_corridor_km; scalability.another_city_needs -> checklist
//   sites: in_plan -> planned; siting.fit -> roof_fit; siting.km_to_330kv -> corridor_km; system.pv_kwp -> siting.pv_kwp
//   siting card: roof.fit -> roof_fit; roof.roof_kwp -> roof_kwp_available; roof.footprint_m2 -> roof_area_m2;
//                km_to_330kv -> corridor_km; security -> anti_theft
import type { AntiTheft, B13Source, CityMetrics, Constant, LabelValue, SiteProps, SitesFC, Siting } from './brief13'

/** an anti-theft measure: the API's status when sent; otherwise a named guide is VERIFIED and "our design standard" an ASSUMPTION */
export function theft(x: string | AntiTheft): AntiTheft {
  if (typeof x === 'string') return { measure: x }
  const basis = x.basis ?? x.source
  const ours = !!basis && /our design standard|no guide/i.test(basis)
  const status = x.status ?? (basis ? (ours ? 'ASSUMPTION' : 'VERIFIED') : undefined)
  return { ...x, source: ours ? undefined : basis, detail: x.detail ?? (ours ? basis : undefined), label: x.label ?? (status ? { label: status, note: basis } : undefined) }
}

/** sources arrive as {text, url, status} (current engine), as plain strings (earlier copies) or as Source objects */
export function src(x: unknown): B13Source {
  if (typeof x === 'string') return { name: x, url: '', licence: '', retrieved: '' }
  const o = (x ?? {}) as Record<string, unknown>
  if (typeof o.text === 'string') return { name: o.text, url: typeof o.url === 'string' ? o.url : '', licence: '', retrieved: '', status: typeof o.status === 'string' ? o.status : undefined }
  return o as unknown as B13Source
}

/** sentence labels joined with their machine-readable statuses */
function withStatus(labels: Record<string, unknown> | null | undefined, status: Record<string, string> | null | undefined, prefix = ''): Record<string, LabelValue> {
  const out: Record<string, LabelValue> = {}
  for (const [k, v] of Object.entries(labels ?? {})) {
    if (k === 'constants' || (v && typeof v === 'object' && !('label' in (v as object)))) continue
    const st = status?.[k]
    if (typeof v === 'string') out[prefix + k] = st && !/per constant/i.test(st) ? { label: st, note: v } : v
    else if (v) out[prefix + k] = v as LabelValue
  }
  return out
}

export function normMetrics(raw: CityMetrics): CityMetrics {
  const r = raw as CityMetrics & { label_status?: Record<string, string> }
  const S = raw.sustainability as CityMetrics['sustainability'] & { cost_label_status?: Record<string, string> }
  const labels: Record<string, LabelValue> = { ...withStatus(S?.cost_labels, S?.cost_label_status, 'cost_'), ...withStatus(raw.labels as Record<string, unknown>, r.label_status) }
  const lc = (raw.labels as Record<string, unknown> | undefined)?.constants
  const constants: Record<string, Constant> | undefined = lc && typeof lc === 'object' ? { ...(lc as Record<string, Constant>), ...raw.constants } : raw.constants
  const f = raw.feasibility ?? ({} as CityMetrics['feasibility'])
  const sc = raw.scalability
  return {
    ...raw,
    city_name: raw.city_name ?? raw.name,
    labels, constants,
    sources: (raw.sources ?? []).map(src),
    feasibility: { ...f, median_corridor_km: f.median_corridor_km ?? f.km_to_330kv_median, security: f.security?.map(theft) },
    scalability: sc ? { ...sc, checklist: sc.checklist ?? sc.another_city_needs } : sc,
  }
}

export function normSites(raw: SitesFC): SitesFC {
  const feats = (raw.features ?? []).map((ft) => {
    const p = ft.properties as SiteProps & { label_status?: Record<string, string> }
    const s = p.siting ?? {}
    return {
      ...ft,
      properties: {
        ...p,
        planned: p.planned ?? p.in_plan,
        facility_id: p.facility_id ?? null,
        rank_source: p.rank != null ? ('api' as const) : undefined,
        labels: withStatus(p.labels, p.label_status) as SiteProps['labels'],
        siting: { ...s, roof_fit: s.roof_fit ?? s.fit, corridor_km: s.corridor_km ?? s.km_to_330kv, pv_kwp: s.pv_kwp ?? p.system?.pv_kwp ?? null, battery_kwh: s.battery_kwh ?? p.system?.battery_kwh ?? null },
      },
    }
  })
  return { ...raw, features: feats, sources: raw.sources?.map(src) }
}

type RawSiting = Siting & {
  roof?: { buildings?: number; footprint_m2?: number; largest_m2?: number; roof_kwp?: CityMetrics['impact']['csh_with']; fit?: Siting['roof_fit'] }
  km_to_330kv?: number; security?: (string | AntiTheft)[]; label_status?: Record<string, string>
}
export function normSiting(raw: RawSiting): Siting {
  return {
    ...raw,
    roof_fit: raw.roof_fit ?? raw.roof?.fit ?? 'ground',
    roof_kwp_available: raw.roof_kwp_available ?? raw.roof?.roof_kwp,
    roof_area_m2: raw.roof_area_m2 ?? raw.roof?.footprint_m2,
    buildings: raw.buildings ?? raw.roof?.buildings,
    corridor_km: raw.corridor_km ?? raw.km_to_330kv,
    anti_theft: (raw.anti_theft ?? raw.security ?? []).map(theft),
    new_line_km: raw.new_line_km ?? 0,
    labels: withStatus(raw.labels as Record<string, unknown>, raw.label_status),
    sources: (raw.sources ?? []).map(src),
  }
}
