// The brief 13 investment brief: one printable page for a city plan (city, budget, outage, sectors), from the same
// sites collection and rule as the Funder plan page and the planner agent. Every figure is an engine result or a sum.
import { useMemo } from 'react'
import { b13 } from '../api/brief13-client'
import { CITIES, OUTAGE_DAYS, type CityId, type Sector } from '../api/brief13'
import { ALL_SECTORS, download, PLAN_RULE, planCity, planCsv, type PlanSite } from '../api/cityplan'
import { Icon, Loading } from '../components/ui'
import { Empty, SourceBadge } from '../city/bits'
import { full, naira, nairaKwh, pt, ROOF, rv, SECTOR_NAME, share } from '../city/format'
import { SectorTag } from '../city/panels'
import { useAsync } from '../hooks'
import { Link, useLocation } from '../router'

export function CityBriefPage() {
  const { search } = useLocation()
  const q = new URLSearchParams(search)
  const city = (CITIES.find((c) => c.id === q.get('city'))?.id ?? 'maiduguri') as CityId
  const qd = Number(q.get('days'))
  const days = (OUTAGE_DAYS as readonly number[]).includes(qd) ? qd : 60
  const budget = Math.max(0, Number(q.get('budget')) || 2e9)
  const sectors = (q.get('sectors')?.split(',').filter((x) => (ALL_SECTORS as string[]).includes(x)) as Sector[] | undefined) ?? ALL_SECTORS
  const secs = sectors.length ? sectors : ALL_SECTORS
  const info = CITIES.find((c) => c.id === city)!
  const sites = useAsync(() => b13.sites(city), [city])
  const met = useAsync(() => b13.metrics(city, days), [city, days])
  const m = met.data?.data
  const price = m?.constants?.DIESEL_NGN_PER_L?.value
  const plan = useMemo(() => planCity((sites.data?.data.features ?? []).map((f) => ({ ...f.properties, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] }) as PlanSite), budget, days, secs, typeof price === 'number' ? price : null), [sites.data, budget, days, secs.join(), price]) // eslint-disable-line react-hooks/exhaustive-deps

  if (sites.loading || met.loading) return <Loading what="Preparing the brief" />
  if (sites.error || !m) return <Empty>{(sites.error ?? met.error)?.message ?? 'The city build is not available.'}</Empty>
  const t = plan.totals
  const fits = plan.funded.reduce((a, r) => ({ ...a, [r.roof_fit ?? 'unknown']: (a[r.roof_fit ?? 'unknown'] ?? 0) + 1 }), {} as Record<string, number>)
  const cost = m.sustainability.cost_per_kwh_ngn
  const sol = rv(cost.solar), dsl = rv(cost.diesel), gas = rv(cost.gas_support)

  return (
    <article className="brief" style={{ maxWidth: 980, margin: '0 auto' }}>
      <div className="row between no-print" style={{ marginBottom: 12 }}>
        <Link to="/plan">Back to the Funder plan</Link>
        <div className="row">
          <button className="btn small" onClick={() => download(`wardlight-brief-${city}-${Math.round(budget)}-${days}d.csv`, planCsv(plan, info.name, m.data_version))}><Icon name="download" /> CSV</button>
          <button className="btn small primary" onClick={() => window.print()}><Icon name="print" /> Print or save as PDF</button>
        </div>
      </div>
      <p className="kicker">Investment brief · brief 13 · power for a city the grid can't protect <SourceBadge src={sites.data?.src} /></p>
      <h1>{info.name}, {info.state} State: {naira(budget)} to keep critical services running through a {days}-day line cut</h1>
      <p>Sectors: {secs.map((x) => SECTOR_NAME[x]).join(', ')}. {PLAN_RULE}</p>

      <div className="metrics" style={{ margin: '16px 0' }}>
        <div><div className="kicker">Sites funded</div><div className="metric">{full(t.funded)}<small> of {full(t.candidates)}</small></div></div>
        <div><div className="kicker">Critical service-hours kept</div><div className="metric">{share(t.share_today)} → {share(t.share_with_funded)}</div><div className="small muted">today, then with the funded sites; {share(t.share_with_every_site)} if every site is built</div></div>
        <div><div className="kicker">Diesel avoided in the window</div><div className="metric">{full(t.diesel_l_avoided)} L</div><div className="small muted">{t.diesel_ngn_avoided != null ? naira(t.diesel_ngn_avoided) : ''}</div></div>
        <div><div className="kicker">Capex</div><div className="metric">{naira(t.spent_ngn)}</div><div className="small muted">{naira(t.remaining_ngn)} of the budget left</div></div>
      </div>

      <h2>By sector</h2>
      <table className="table">
        <thead><tr><th>Sector</th><th>Funded</th><th>Kept today</th><th>Kept with the plan</th><th>Capex funded</th><th>To fund the rest</th></tr></thead>
        <tbody>{ALL_SECTORS.filter((x) => plan.by_sector[x]?.in_scope).map((x) => { const g = plan.by_sector[x]!; return <tr key={x}><td><SectorTag sector={x} /></td><td className="mono">{full(g.funded)} of {full(g.sites)}</td><td className="mono">{share(g.share_today)}</td><td className="mono">{share(g.share_with_funded)}</td><td className="mono">{naira(g.capex_funded_ngn)}</td><td className="mono">{naira(g.capex_to_fund_the_rest_ngn)}</td></tr> })}</tbody>
      </table>

      <h2>Cost per kWh delivered</h2>
      <p>Solar and storage {nairaKwh(sol.point)} per kWh ({nairaKwh(sol.lo)} to {nairaKwh(sol.hi)}); diesel {nairaKwh(dsl.point)}.
        {city === 'maiduguri' && pt(cost.gas_support) !== null && <> The gas plant's federal operating support is about {nairaKwh(gas.point)} per kWh at its reported output, so when the plant runs it costs less than solar: the plan works alongside the plant and replaces the diesel that critical sites burn when the line or the plant fails.</>}</p>

      <h2>Security and siting of the funded sites</h2>
      <p>{Object.entries(fits).map(([k, v]) => `${full(v)} ${(ROOF[k] ?? k).toLowerCase()}`).join('; ')}. No new exposed line: every system sits inside the site's own compound. Batteries in a lockable room or a steel cage.</p>

      <h2>Funded sites, in plan order</h2>
      <table className="table">
        <thead><tr><th>#</th><th>Site</th><th>System</th><th>Capex</th><th>Cumulative</th><th>Hours kept (today, with)</th><th>Roof</th></tr></thead>
        <tbody>{plan.funded.map((r) => (
          <tr key={r.id}><td className="mono">{r.order}</td><td>{r.name}<div className="small muted">{SECTOR_NAME[r.sector]}{r.lga ? `, ${r.lga}` : ''} · <span className="mono">{r.id}</span></div></td>
            <td className="mono small">{r.pv_kwp} kWp, {r.battery_kwh} kWh</td><td className="mono">{naira(r.capex_ngn)}</td><td className="mono">{naira(r.cumulative_ngn)}</td>
            <td className="mono small">{full(r.today_h)}, {full(r.with_h)} of {full(r.needed_h)}</td><td className="small">{ROOF[r.roof_fit ?? 'unknown'] ?? r.roof_fit}</td></tr>))}</tbody>
      </table>

      <h2>Labels and sources</h2>
      <ul className="small">
        <li>Grid supply is modelled from NERC's band promise, promised and not measured. Critical loads are archetypes (SEforALL priority-1 loads for health sites; survey yield and an assumed head for boreholes; a ColdHubs-type room per market), not measured per site.</li>
        <li>Diesel at N{typeof price === 'number' ? price.toLocaleString('en-US') : 'n/a'} per litre, the national average for May 2026; Borno prices differ.</li>
        <li>Sites already powered on site (the UNIMAID/UMTH solar plant) are not in the plan.</li>
        {(m.sources ?? []).slice(0, 8).map((s, i) => <li key={i}>{s.url ? <a href={s.url}>{s.name}</a> : s.name}</li>)}
      </ul>
      <p className="small muted">Data version <span className="mono">{m.data_version}</span>. Wardlight, IAS Global Energy Hackathon 2026, brief 13.</p>
    </article>
  )
}
