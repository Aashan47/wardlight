import { Fragment, useEffect, useRef, type ReactNode } from 'react'
import { CITIES, type CityId, type CityMetrics, type Constant, type CorridorFC, type DataSource, type EvidenceLabel, type Range } from '../api/brief13'
import { LabelChip, SourceBadge } from './bits'
import { compact, full, labelNote, labelOf, labelsFor, naira, nairaKwh, pt, ratio, rv, share, span, tw, rowLabel, weakestOf } from './format'

export type MetricKey = 'impact' | 'innovation' | 'sustainability' | 'feasibility' | 'scalability'

/** The brief's words (verbatim), the labels and constants behind each metric, and a method used when the API sends none. */
export const BRIEF: Record<MetricKey, { title: string; weight: number; words: string; labelKeys: string[]; constants: string[]; section: string; method: string }> = {
  impact: {
    title: 'Impact', weight: 25, words: 'Hours of critical service maintained during a line outage, and diesel litres avoided',
    labelKeys: ['scenario_today', 'scenario_today_diesel', 'scenario_with', 'supply', 'diesel', 'diesel_price', 'water', 'water_works', 'cold', 'people_served', 'sums', 'csh', 'diesel_l_avoided'],
    constants: ['BH_', 'PUMP_', 'SOLAR_BH', 'WATER_', 'COLD', 'GEN', 'DIESEL_'], section: 'sec-map',
    method: 'For every site and every critical load: the hours in the outage window the load is needed, and the hours it is served, summed over the city. Today without backup counts grid hours only, and the line is cut for the whole window. Today with diesel is a labelled scenario in which every site has a generator and fuel. With the plan, the site\'s own solar and battery carry its critical loads and no diesel is burned. Diesel avoided is the fuel a generator would burn to deliver what the solar delivers in the window.',
  },
  innovation: {
    title: 'Innovation', weight: 25, words: 'Distributed or community-owned approach that reduces dependence on one vulnerable line',
    labelKeys: ['local_share', 'scenario_with', 'supply', 'water', 'cold', 'corridor', 'ownership'], constants: [], section: 'sec-map',
    method: 'The share of the critical energy needed during the outage that is made and stored on site, today and with the plan. Every planned system sits inside an existing compound and can run on its own, so the plan adds no exposed line. The single point of failure is the mapped 330 kV corridor, counted from OpenStreetMap.',
  },
  sustainability: {
    title: 'Sustainability', weight: 25, words: 'Lower lifetime cost per kWh than diesel or the subsidized gas plant; emissions avoided; assets protected by local stakeholders',
    labelKeys: ['cost_solar', 'cost_diesel', 'cost_gas_support', 'cost_breakeven', 'gas_support', 'diesel', 'diesel_price', 'ownership', 'co2'],
    constants: ['COST_', 'BATTERY_', 'OM_', 'SYSTEM_', 'REPLACEMENT_', 'FX_', 'GEN', 'DIESEL_', 'MEPP_', 'CO2_'], section: 'sec-cost',
    method: 'Solar plus storage: capital cost, operation and maintenance and a battery replacement over the system life, divided by the kWh it delivers. Diesel: fuel at the NBS pump price times litres per kWh, plus generator costs where sourced. Gas plant: the federal operating support alone, divided by the plant\'s output over a stated range; tariff and capital are not included. Emissions: litres avoided times the EPA factor for diesel. Local protection: who owns, pays for, guards and repairs each kind of site.',
  },
  feasibility: {
    title: 'Feasibility', weight: 15, words: 'Installable and maintainable under real security conditions',
    labelKeys: ['roof', 'roof_fit', 'security', 'anti_theft'], constants: ['ROOF_', 'PV_KWP', 'BATTERY_'], section: 'sec-sites',
    method: 'For each site, the PV it needs against the roof area of the mapped buildings around it: it fits on the roof, partly, or goes on the ground inside the wall. Batteries sit in a lockable room or a steel cage. No site needs a new line. Distance to the 330 kV corridor is measured to the mapped route. Anti-theft measures are our design standard unless a guide is cited.',
  },
  scalability: {
    title: 'Scalability', weight: 10, words: 'Applicable to other conflict-affected or grid-isolated cities',
    labelKeys: ['scalability', 'plan_minutes'], constants: [], section: 'sec-top',
    method: 'Damaturu and Yola run through the same pipeline as Maiduguri, with the same kinds of input. The build time is the engine\'s own measured run time for the city. Switch the city at the top of the page to see each one\'s plan.',
  },
}

export interface Others { id: CityId; m?: CityMetrics }
type Row = [string, string, string | null, string[]]
interface View { headline: ReactNode; unit: string; range: string | null; label: EvidenceLabel | null; body: ReactNode; rows: Row[]; extra?: ReactNode }

const pctRange = (r: Range) => span(r, (n) => share(n))
const km = (n: number | null) => (n === null ? 'n/a' : n < 10 ? n.toFixed(1) : full(n))

export function viewOf(k: MetricKey, m: CityMetrics, corridor: CorridorFC | null, others: Others[]): View {
  const lab = weakestOf(m, BRIEF[k].labelKeys, BRIEF[k].constants)
  const I = m.impact, N = m.innovation, S = m.sustainability, F = m.feasibility
  if (k === 'impact') {
    const w = ratio(I.csh_with, I.csh_needed), t = ratio(I.csh_today, I.csh_needed), d = ratio(I.csh_today_diesel, I.csh_needed)
    const L = rv(I.diesel_l_avoided), ng = rv(I.diesel_ngn_avoided)
    const water = tw(I.water_m3_per_day_kept), ppl = tw(I.people_served)
    const opt = (cond: boolean, r: Row): Row[] => (cond ? [r] : [])
    return {
      headline: share(w.point), unit: 'of critical service-hours kept with the plan', range: pctRange(w), label: lab,
      body: (
        <>
          <div className="trio" role="list" aria-label="Share of critical service-hours kept">
            <TrioBar name="Today, no backup" r={t} cls="b-today" />
            <TrioBar name="Today, with diesel" r={d} cls="b-diesel" />
            <TrioBar name="With the plan, no diesel" r={w} cls="b-plan" strong />
          </div>
          <p className="tile-foot"><b className="mono">{full(L.point)}</b> litres of diesel not burned{span(L, compact) && <span className="muted"> (range {span(L, compact)})</span>}{ng.point !== null && <>, worth <b className="mono">{naira(ng.point)}</b> at the pump</>}</p>
        </>
      ),
      rows: [
        ['Critical service-hours needed', full(pt(I.csh_needed)), span(rv(I.csh_needed), full), ['scenario_today']],
        ['Kept today, no backup', full(pt(I.csh_today)), span(rv(I.csh_today), full), ['scenario_today', 'supply']],
        ['Kept today, with diesel (labelled scenario)', full(pt(I.csh_today_diesel)), span(rv(I.csh_today_diesel), full), ['scenario_today_diesel']],
        ['Kept with the plan', full(pt(I.csh_with)), span(rv(I.csh_with), full), ['scenario_with']],
        ['Diesel litres avoided in the window', full(L.point), span(L, full), ['diesel']],
        ['Diesel cost avoided', naira(ng.point), span(ng, naira), ['diesel', 'diesel_price']],
        ...opt(pt(I.today_diesel_scenario?.ngn) !== null, ['Fuel bill if every site ran diesel today', naira(pt(I.today_diesel_scenario?.ngn)), span(rv(I.today_diesel_scenario?.ngn), naira), ['scenario_today_diesel', 'diesel', 'diesel_price']]),
        ...opt(water.with.point !== null && water.with.point > 0, ['Water pumped, m³ a day: today, with the plan', `${water.today ? full(water.today.point) : 'n/a'} to ${full(water.with.point)}`, null, ['water', 'water_works']]),
        ...opt(ppl.with.point !== null && ppl.with.point > 0, ['People that water serves: today, with the plan', `${ppl.today ? full(ppl.today.point) : 'n/a'} to ${full(ppl.with.point)}`, span(ppl.with, full), ['people_served']]),
        ...opt(pt(I.cold_rooms_kept) !== null, ['Market cold rooms kept running', full(pt(I.cold_rooms_kept)), null, ['cold']]),
      ],
    }
  }
  if (k === 'innovation') {
    const ls = tw(N.local_share)
    const kmv = pt(N.corridor.km_330) ?? corridor?.km_330 ?? null, twr = pt(N.corridor.towers) ?? corridor?.towers ?? null
    const elsewhere = N.corridor.applies_to_city === false
    return {
      headline: share(ls.with.point), unit: 'of critical energy made on site during the outage', range: pctRange(ls.with), label: lab,
      body: (
        <ul className="facts">
          {ls.today && <li>today <b className="mono">{share(ls.today.point)}</b>{(ls.today.point ?? 0) > 0 && (N.sites_by_sector?.water ?? 0) > 0 ? ', from existing solar boreholes' : ''}</li>}
          <li><b className="mono">{full(N.sites)}</b> sites that can run on their own</li>
          <li><b className="mono">{full(N.new_line_km)} km</b> of new exposed line</li>
          {kmv !== null && <li>{elsewhere ? 'the Gombe to Maiduguri corridor: ' : 'against '}<b className="mono">{full(kmv)} km</b> of mapped 330 kV line{twr !== null && <> and <b className="mono">{full(twr)}</b> towers</>}</li>}
          {elsewhere && N.corridor.note && <li className="muted">{N.corridor.note}</li>}
        </ul>
      ),
      rows: [
        ['Critical energy made on site, today', ls.today ? share(ls.today.point) : 'n/a', null, ['supply', 'water']],
        ['Critical energy made on site, with the plan', share(ls.with.point), pctRange(ls.with), ['scenario_with']],
        ...(N.local_share && typeof N.local_share === 'object' && 'critical_kwh_needed' in N.local_share && N.local_share.critical_kwh_needed != null ? [['Critical energy needed in the window, kWh', full(N.local_share.critical_kwh_needed), null, []] as Row] : []),
        ['Sites that can run on their own', full(N.sites), null, []],
        ...Object.entries(N.sites_by_sector ?? {}).map(([s, n]) => [`  of which ${s === 'cold' ? 'market cold rooms' : s === 'water' ? 'water points' : 'health sites'}`, full(n as number), null, []] as Row),
        ['New exposed line', `${full(N.new_line_km)} km`, null, []],
        ['Mapped 330 kV line (OpenStreetMap)', kmv === null ? 'n/a' : `${full(kmv)} km`, null, []],
        ['Towers on it', twr === null ? 'n/a' : full(twr), null, []],
        ...(pt(N.corridor.km_132) !== null ? [['Mapped 132 kV line', `${full(pt(N.corridor.km_132))} km`, null, []] as Row] : []),
      ],
      extra: N.corridor.source ? <p className="small muted">Corridor: {N.corridor.source}{N.corridor.box ? `. Box: ${N.corridor.box}` : ''}.</p> : null,
    }
  }
  if (k === 'sustainability') {
    const c = S.cost_per_kwh_ngn, so = rv(c.solar), di = rv(c.diesel), ga = rv(c.gas_support), co = rv(S.co2_t_avoided)
    const gt = rv(c.gas_tariff_cost_reflective ?? S.gas_tariff_cost_reflective?.ngn_per_kwh), dl = rv(c.diesel_fuel_only)
    const position = S.gas_position?.text ?? m.headline_alongside
    const yr = rv(S.co2_t_avoided_per_year ?? S.co2_t_avoided_per_year_upper)
    return {
      headline: <>{nairaKwh(so.point)}<small>/kWh</small></>, unit: 'lifetime cost per kWh, solar plus storage', range: span(so, nairaKwh), label: lab,
      body: (
        <>
          {position && <p className="alongside sm" role="note">{position}</p>}
          <ul className="facts">
            <li>Diesel <b className="mono">{nairaKwh(di.point)}</b> per kWh{dl.point !== null ? <>, fuel alone <b className="mono">{nairaKwh(dl.point)}</b></> : <>, fuel only</>}</li>
            <li>Gas plant: support <b className="mono">{nairaKwh(ga.point)}</b>{gt.point !== null && <>, cost-reflective tariff <b className="mono">{nairaKwh(gt.point)}</b></>} per kWh</li>
            <li><b className="mono">{full(co.point)}</b> t CO₂ avoided in the outage{yr.point !== null && <>, up to <b className="mono">{full(yr.point)}</b> t a year</>}</li>
          </ul>
          {S.ownership?.length > 0 && <p className="tile-foot">Who owns, pays, guards and repairs: a proposed model for each sector</p>}
        </>
      ),
      rows: [
        ['Solar plus storage, N per kWh, lifetime', full(so.point), span(so, full), ['cost_solar']],
        ...(S.cost_arms?.daily_cycle ? [['Solar plus storage, daily-cycle arm, N per kWh', full(pt(S.cost_arms.daily_cycle.cost_per_kwh_ngn)), span(rv(S.cost_arms.daily_cycle.cost_per_kwh_ngn), full), ['cost_solar']] as Row] : []),
        ['Diesel, N per kWh', full(di.point), span(di, full), ['cost_diesel', 'diesel', 'diesel_price']],
        ...(dl.point !== null ? [['Diesel, fuel only (lower bound), N per kWh', full(dl.point), span(dl, full), ['diesel', 'diesel_price']] as Row] : []),
        ['Gas plant operating support, N per kWh', full(ga.point), span(ga, full), ['gas_support', 'cost_gas_support']],
        ...(gt.point !== null ? [['Gas plant cost-reflective tariff, N per kWh', full(gt.point), null, ['gas_tariff']] as Row] : []),
        ...Object.entries(S.gas_support_at_mw ?? {}).sort((x, y) => Number(x[0]) - Number(y[0])).map(([mw, v]) => [`  at ${mw} MW average delivered`, full(v), null, ['cost_gas_support']] as Row),
        ['Break-even average output, MW', pt(S.gas_breakeven_mw) === null ? 'n/a' : (pt(S.gas_breakeven_mw)!).toFixed(1), span(rv(S.gas_breakeven_mw), (n) => n.toFixed(1)), ['cost_breakeven']],
        ['Break-even output, MWh a month', full(pt(S.gas_breakeven_mwh_per_month)), span(rv(S.gas_breakeven_mwh_per_month), full), ['cost_breakeven']],
        ['CO₂ avoided in the outage, t', full(co.point), span(co, full), ['diesel', 'co2']],
        ...(yr.point !== null ? [['CO₂ avoided a year, upper end, t', full(yr.point), span(yr, full), ['diesel']] as Row] : []),
        ...(pt(S.capex_ngn) !== null ? [['Capital cost of every system in the plan', naira(pt(S.capex_ngn)), span(rv(S.capex_ngn), naira), ['cost_solar']] as Row] : []),
      ],
    }
  }
  if (k === 'feasibility') {
    const { fits, partial, ground } = F.roof_fit
    const unknown = F.roof_fit.unknown ?? 0
    const total = F.sites ?? fits + partial + ground + unknown
    const med = rv(F.median_corridor_km)
    return {
      headline: <>{full(fits)}<small> of {full(total)}</small></>, unit: 'sites fit their solar on the roofs around them', range: null, label: lab,
      body: (
        <>
          <div className="segbar" role="img" aria-label={`${fits} fit on the roof, ${partial} partly, ${ground} on the ground inside the wall${unknown ? `, ${unknown} with no mapped buildings nearby` : ''}`}>
            {([['fits', fits], ['partial', partial], ['ground', ground], ['unknown', unknown]] as [string, number][]).map(([k2, v]) => v > 0 && <span key={k2} className={`sg-${k2}`} style={{ flexGrow: v }} />)}
          </div>
          <ul className="legend small"><li><span className="key sg-fits" />roof {full(fits)}</li><li><span className="key sg-partial" />partly {full(partial)}</li><li><span className="key sg-ground" />ground, inside the wall {full(ground)}</li>{unknown > 0 && <li><span className="key sg-unknown" />roof not known {full(unknown)}</li>}</ul>
          <p className="tile-foot"><b className="mono">{full(F.new_line_km ?? 0)} km</b> of new line{med.point !== null && <>; median <b className="mono">{km(med.point)} km</b> from the 330 kV line</>}</p>
        </>
      ),
      rows: [
        ['Fit on the roofs around them', full(fits), null, ['roof']],
        ['Partly on the roof', full(partial), null, ['roof']],
        ['Ground-mounted inside the wall', full(ground), null, ['roof']],
        ...(unknown ? [['Roof not known: no mapped buildings nearby', full(unknown), null, ['roof']] as Row] : []),
        ['New line', `${full(F.new_line_km ?? 0)} km`, null, []],
        ...(med.point !== null ? [['Median distance to the 330 kV line', `${km(med.point)} km`, span(med, (n) => n.toFixed(1)), []] as Row] : []),
        ...(pt(F.battery_kwh_total) !== null ? [['Battery storage across the plan', `${full(pt(F.battery_kwh_total))} kWh`, null, []] as Row] : []),
      ],
      extra: F.security?.length ? <><h3 className="dh">Anti-theft measures, every site</h3><ul className="theft">{F.security.map((x) => { const o = typeof x === 'string' ? { measure: x } : x; return <li key={o.measure}><span>{o.measure}{o.detail && <span className="small muted"> ({o.detail})</span>}</span><span className="row" style={{ gap: 6 }}>{o.source && <span className="small muted">{o.source}</span>}<LabelChip label={labelOf(o.label ?? m.labels.security)} note={labelNote(o.label ?? m.labels.security)} /></span></li> })}</ul></> : null,
    }
  }
  const ready = others.filter((o) => o.m)
  const sc = m.scalability
  return {
    headline: <>{full(ready.length)}<small> cities</small></>, unit: 'planned by the same pipeline', range: null, label: lab,
    body: (
      <>
        <ul className="cities">
          {others.map((o) => {
            const c = CITIES.find((x) => x.id === o.id)!
            const w = o.m ? ratio(o.m.impact.csh_with, o.m.impact.csh_needed).point : null
            const t = o.m ? ratio(o.m.impact.csh_today, o.m.impact.csh_needed).point : null
            return (
              <li key={o.id} className={o.id === m.city ? 'cur' : ''}>
                <span>{c.name}<small> {o.m ? `${full(o.m.innovation.sites)} sites` : c.state}</small></span>
                {o.m ? <span className="mono small">{share(t)} <span aria-hidden="true">→</span><span className="sr-only">to</span> <b>{share(w)}</b></span> : <span className="small muted">not available</span>}
              </li>
            )
          })}
        </ul>
        {sc?.build_seconds != null && <p className="tile-foot"><b className="mono">{sc.build_seconds} s</b> for the engine to rebuild this city's plan</p>}
      </>
    ),
    rows: [
      ...others.map((o) => [`${CITIES.find((x) => x.id === o.id)!.name}: service-hours kept, today to plan`, o.m ? `${share(ratio(o.m.impact.csh_today, o.m.impact.csh_needed).point)} to ${share(ratio(o.m.impact.csh_with, o.m.impact.csh_needed).point)}` : 'not available', null, []] as Row),
      ...(sc?.build_seconds != null ? [['Engine run time for this city', `${sc.build_seconds} s`, null, []] as Row] : []),
    ],
    extra: (sc?.checklist?.length || sc?.data) ? (
      <>
        {sc?.checklist?.length ? <><h3 className="dh">What another city needs to copy this</h3><ul className="checklist">{sc.checklist.map((x) => <li key={x}>{x}</li>)}</ul></> : null}
        {sc?.data ? <><h3 className="dh">This city's data</h3><dl className="own-grid">{Object.entries(sc.data).map(([kk, v]) => <Fragment key={kk}><dt>{kk}</dt><dd>{v}</dd></Fragment>)}</dl></> : null}
      </>
    ) : null,
  }
}

function TrioBar({ name, r, cls, strong }: { name: string; r: Range; cls: string; strong?: boolean }) {
  return (
    <div className={`trio-r${strong ? ' strong' : ''}`} role="listitem" aria-label={`${name}: ${share(r.point)}`}>
      <span className="trio-n">{name}</span>
      <span className="track"><span className={`bar ${cls}`} style={{ width: `${(r.point ?? 0) * 100}%` }} /></span>
      <span className="mono trio-v">{share(r.point)}</span>
    </div>
  )
}

export function Tile({ k, m, corridor, others, src, onOpen }: { k: MetricKey; m: CityMetrics; corridor: CorridorFC | null; others: Others[]; src?: DataSource; onOpen: (k: MetricKey) => void }) {
  const b = BRIEF[k], v = viewOf(k, m, corridor, others)
  return (
    <article className={`tile t-${k}`} aria-labelledby={`tile-${k}`}>
      <header className="tile-h">
        <span className="wpill"><b>{b.title}</b> {b.weight}%</span>
        <span className="row" style={{ gap: 6 }}>{src === 'mock' && <SourceBadge src={src} />}<LabelChip label={v.label} /></span>
      </header>
      <p className="brief-words">“{b.words}”</p>
      <h3 className="tile-num" id={`tile-${k}`}><span className={src === 'mock' ? 'is-mock' : ''}>{v.headline}</span></h3>
      <p className="tile-unit">{v.unit}{v.range && <span className="rangeline"> · range {v.range}</span>}</p>
      <div className="tile-body">{v.body}</div>
      <button type="button" className="tile-open" onClick={() => onOpen(k)} aria-haspopup="dialog">
        Evidence <span aria-hidden="true">→</span><span className="sr-only"> for {b.title}</span>
      </button>
    </article>
  )
}

const STATUS_TEXT: Record<string, string> = { VERIFIED_SECONDARY: 'verified through secondary reports', DERIVED: 'derived from verified figures' }

export function EvidenceDrawer({ k, m, corridor, others, src, onClose }: { k: MetricKey | null; m: CityMetrics | undefined; corridor: CorridorFC | null; others: Others[]; src?: DataSource; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (k && !d.open) d.showModal()
    if (!k && d.open) d.close()
  }, [k])
  const b = k ? BRIEF[k] : null
  const v = k && m ? viewOf(k, m, corridor, others) : null
  const labels = k && m ? labelsFor(m.labels, b!.labelKeys) : []
  const consts: [string, Constant][] = k && m?.constants ? Object.entries(m.constants).filter(([n]) => b!.constants.some((p) => n.startsWith(p))) : []
  const go = (id: string) => { onClose(); setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }), 60) }
  return (
    <dialog ref={ref} className="drawer" onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose() }} aria-labelledby="drawer-title">
      {b && v && m && (
        <div className="drawer-in">
          <header className="row between" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
            <div>
              <p className="kicker">{b.title} · {b.weight}% of the score · evidence</p>
              <h2 id="drawer-title" style={{ margin: 0 }}>{v.headline} <span className="drawer-unit">{v.unit}</span></h2>
            </div>
            <button className="icon-btn" onClick={onClose} aria-label="Close the evidence view"><svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" /></svg></button>
          </header>
          <p className="brief-words" style={{ marginTop: 10 }}>The brief asks: “{b.words}”</p>
          <div className="row" style={{ gap: 8 }}><LabelChip label={v.label} /><SourceBadge src={src} /><span className="small muted">{m.city_name ?? CITIES.find((c) => c.id === m.city)?.name}, {m.days}-day outage{m.data_version ? <>, data version <span className="mono">{m.data_version}</span></> : null}</span></div>
          {v.label && <p className="small muted" style={{ margin: '8px 0 0' }}>The chip shows the weakest label among the inputs below: a headline is only as firm as its least certain input.</p>}

          <h3 className="dh">The numbers</h3>
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>Figure</th><th>Value</th><th>Range</th><th>Label</th></tr></thead>
              <tbody>
                {v.rows.map(([name, val, rng, keys]) => {
                  const l = rowLabel(m, keys)
                  return <tr key={name}><td>{name}</td><td className="mono nowrap">{val}</td><td className="mono nowrap">{rng ?? ''}</td><td>{l && <LabelChip label={l} />}</td></tr>
                })}
              </tbody>
            </table>
          </div>
          {v.extra}

          <h3 className="dh">How it is computed</h3>
          <p>{(k && m.methods?.[k]) || b.method}</p>

          {labels.length > 0 && (
            <>
              <h3 className="dh">What each input rests on</h3>
              <ul className="labels-list">
                {labels.map(([key, val]) => {
                  const url = typeof val === 'object' ? val.url : undefined, srcName = typeof val === 'object' ? val.source : undefined
                  const note = labelNote(val)
                  return (
                    <li key={key}><span className="lk"><LabelChip label={labelOf(val)} /><span className="mono small">{key.replace(/_/g, ' ')}</span></span>{note && <span className="small">{note}</span>}{url ? <a className="small" href={url} target="_blank" rel="noopener">{srcName ?? 'Source'}</a> : srcName ? <span className="small muted">{srcName}</span> : null}</li>
                  )
                })}
              </ul>
            </>
          )}

          {consts.length > 0 && (
            <>
              <h3 className="dh">Constants this run used</h3>
              <div className="table-scroll">
                <table className="table consts">
                  <thead><tr><th>Constant</th><th>Value</th><th>Range</th><th>Status and source</th></tr></thead>
                  <tbody>
                    {consts.map(([n, c]) => (
                      <tr key={n}>
                        <td className="mono small">{n}</td>
                        <td className="mono nowrap">{typeof c.value === 'number' ? (Math.abs(c.value) >= 1000 ? full(c.value) : c.value) : c.value} <span className="muted small">{c.unit}</span></td>
                        <td className="mono nowrap">{c.lo != null && c.hi != null && c.lo !== c.hi ? `${c.lo}–${c.hi}` : ''}</td>
                        <td className="small"><LabelChip label={labelOf(c.status)} note={STATUS_TEXT[c.status ?? ''] ?? null} /> {c.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {m.sources?.length > 0 && (
            <>
              <h3 className="dh">Sources</h3>
              <ul className="src-list">
                {m.sources.map((s, i) => (
                  <li key={i}>
                    <span className="src-h">{s.status && <LabelChip label={labelOf(s.status)} note={STATUS_TEXT[s.status] ?? s.status} />}{s.url && s.url !== '#' ? <a href={s.url} target="_blank" rel="noopener">{s.name}<span className="sr-only"> (opens in a new tab)</span></a> : <span>{s.name}</span>}</span>
                    {(s.licence || s.retrieved) && <span className="small muted">{[s.licence, s.retrieved && `retrieved ${s.retrieved}`].filter(Boolean).join(', ')}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p style={{ marginTop: 18 }}><button className="btn" onClick={() => go(b.section)}>See it on the page</button></p>
        </div>
      )}
    </dialog>
  )
}
