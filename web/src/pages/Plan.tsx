// Funder plan (brief 13): a budget in naira, an outage length and the sectors to protect -> which critical sites the
// budget keeps running when the line is cut, in the city's plan order. The plan is computed in the browser from the
// sites collection with the same rule as the planner agent's rank_city_plan tool (src/api/cityplan.ts); the planner
// and the line watcher run beside it and drive the same controls.
import { useEffect, useMemo, useState } from 'react'
import { api, BASE, MODE } from '../api/client'
import { b13, weakest } from '../api/brief13-client'
import { CITIES, OUTAGE_DAYS, SECTORS, type CityId, type Sector } from '../api/brief13'
import { ALL_SECTORS, download, PLAN_RULE, planCity, planCsv, type PlanSite } from '../api/cityplan'
import { AgentRun } from '../agent/AgentRun'
import { LineWatchPanel } from '../agent/LineWatchPanel'
import { useAgentRun } from '../agent/useAgentRun'
import { Icon, Loading } from '../components/ui'
import { Empty, Segmented, SourceBadge } from '../city/bits'
import { CriticalMap } from '../city/CriticalMap'
import { full, naira, SECTOR_NAME, share } from '../city/format'
import { type MapSite } from '../city/mapdata'
import { SectorDot, SectorTag } from '../city/panels'
import { useAsync, useReducedMotion } from '../hooks'
import { Link, navigate } from '../router'

const DAY_HINT: Record<number, string> = { 14: 'two weeks', 40: 'the 2024 cut', 60: "the brief's two months" }
const DEFAULT_BUDGET = 2e9 // one month of the gas plant's federal operating support (brief 13, refs 5 and 6)
const STEP = 1e7

export function PlanPage() {
  const reduced = useReducedMotion()
  const [city, setCity] = useState<CityId>('maiduguri')
  const [days, setDays] = useState<number>(60)
  const [sectors, setSectors] = useState<Sector[]>(ALL_SECTORS)
  const [budget, setBudget] = useState<number>(DEFAULT_BUDGET)
  const [all, setAll] = useState(false)
  const [sel, setSel] = useState<string | null>(null)
  const [pick, setPick] = useState<string | null>(null)
  const [own, setOwn] = useState('')
  const cityInfo = CITIES.find((c) => c.id === city)!

  const sites = useAsync(() => b13.sites(city), [city])
  const met = useAsync(() => b13.metrics(city, 60), [city])
  const cor = useAsync(() => b13.corridor(), [])
  const recs = useAsync(() => (MODE === 'live' ? api.recordings() : Promise.resolve({ recorded: true, recordings: [] })), [])
  const planners = (recs.data?.recordings ?? []).filter((r) => r.agent === 'planner' && r.question)
  useEffect(() => { if (planners.length && !pick) setPick(planners.find((r) => r.name.includes('maiduguri'))?.name ?? planners[0].name) }, [planners, pick])
  const chosen = planners.find((r) => r.name === pick)
  const run = useAgentRun('planner')
  const s = run.state

  const m = met.data?.data
  const price = m?.constants?.DIESEL_NGN_PER_L?.value
  const dieselPrice = typeof price === 'number' ? price : null
  const planSites: PlanSite[] = useMemo(() => (sites.data?.data.features ?? []).map((f) => ({ ...f.properties, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] })), [sites.data])
  const maxBudget = useMemo(() => Math.ceil(planSites.filter((x) => x.rank != null && sectors.includes(x.sector)).reduce((a, x) => a + (x.system?.capex_ngn ?? 0), 0) / STEP) * STEP, [planSites, sectors])

  // the agent drives the controls: its rank_city_plan call sets city, budget, days and sectors
  const call = s.tools.find((t) => t.name === 'rank_city_plan')
  const a = call?.args ?? {}
  const agentBudget = Number(s.answer?.totals?.budget_ngn ?? (a.currency === 'USD' ? NaN : a.budget)) || undefined
  useEffect(() => {
    if (!call) return
    const c = String(a.city ?? '').toLowerCase()
    if (CITIES.some((x) => x.id === c)) setCity(c as CityId)
    if (typeof a.days === 'number' && (OUTAGE_DAYS as readonly number[]).includes(a.days)) setDays(a.days)
    if (Array.isArray(a.sectors) && a.sectors.length) setSectors(ALL_SECTORS.filter((x) => (a.sectors as string[]).includes(x)))
  }, [call]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (agentBudget) setBudget(agentBudget) }, [agentBudget])

  const plan = useMemo(() => planCity(planSites, budget, days, sectors, dieselPrice), [planSites, budget, days, sectors, dieselPrice])
  const agentFunded = useMemo(() => s.answer?.funded?.map((f) => (typeof f === 'string' ? f : f.unique_id)), [s.answer])
  const [lit, setLit] = useState(0)
  useEffect(() => { if (!agentFunded) setLit(0) }, [agentFunded])
  useEffect(() => {
    if (!agentFunded) return
    if (reduced) { setLit(agentFunded.length); return }
    if (lit >= agentFunded.length) return
    const h = setTimeout(() => setLit((n) => Math.min(agentFunded.length, n + Math.max(1, Math.ceil(agentFunded.length / 60)))), 35)
    return () => clearTimeout(h)
  }, [agentFunded, lit, reduced])
  const funded = useMemo(() => (agentFunded && s.status !== 'idle' ? new Set(agentFunded.slice(0, lit)) : new Set(plan.funded.map((r) => r.id))), [agentFunded, lit, plan, s.status])
  const considering = s.status === 'running' && !!call && !agentFunded

  const mapSites: MapSite[] = useMemo(() => plan.rows.map((r) => {
    const on = funded.has(r.id)
    const today = r.needed_h ? r.today_h / r.needed_h : 0, withP = r.needed_h ? r.with_h / r.needed_h : 0
    return { id: r.id, name: r.name, sector: r.sector, kw: planSites.find((x) => x.id === r.id)?.kw ?? 1, lon: r.lon, lat: r.lat, glow: on ? withP : considering ? 0.35 : today, planned: true, rank: r.rank, today, withPlan: withP }
  }), [plan, funded, considering, planSites])

  const reset = () => { if (s.status !== 'idle') run.reset() }
  const toggle = (x: Sector) => { reset(); setSectors((p) => (p.includes(x) ? (p.length > 1 ? p.filter((y) => y !== x) : p) : ALL_SECTORS.filter((y) => p.includes(y) || y === x))) }
  const go = (body: Record<string, unknown>) => run.start({ path: '/agent/plan', body })
  const t = plan.totals
  const shown = all ? plan.rows : plan.rows.slice(0, 15)
  const selRow = plan.rows.find((r) => r.id === sel)
  const query = `city=${city}&budget=${Math.round(budget)}&days=${days}&sectors=${sectors.join(',')}`
  const src = weakest([sites.data?.src, met.data?.src])

  const controls = (
    <div className="stack">
      {MODE === 'live' && planners.length > 0 && (
        <fieldset style={{ border: 'none', margin: 0, padding: 0 }}>
          <legend className="small" style={{ fontWeight: 500, marginBottom: 6 }}>Recorded sessions</legend>
          <div className="chips">
            {planners.map((r) => <button key={r.name} type="button" className={`chip pick ${pick === r.name ? 'on' : ''}`} aria-pressed={pick === r.name} onClick={() => { run.reset(); setPick(r.name) }} title={r.what}>{r.what}</button>)}
          </div>
        </fieldset>
      )}
      <div className="row">
        <button className="btn primary" disabled={s.status === 'running' || !chosen} onClick={() => go({ question: chosen!.question, recorded: true, recording: chosen!.name })}>
          <Icon name="play" /> {s.status === 'running' ? 'Running…' : 'Replay this session'}
        </button>
        {s.status !== 'idle' && s.status !== 'running' && <button className="btn" onClick={run.reset}>Clear</button>}
      </div>
      {MODE === 'live' && (
        <form className="field" onSubmit={(e) => { e.preventDefault(); if (own.trim()) go({ question: own.trim() }) }}>
          <label htmlFor="own-q" className="small">Or ask your own question</label>
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            <input id="own-q" type="text" value={own} onChange={(e) => setOwn(e.target.value)} placeholder="N800 million for Yola clinics, a 40 day cut" maxLength={600} />
            <button className="btn" type="submit" disabled={!own.trim() || s.status === 'running'}>Ask</button>
          </div>
          <span className="small muted">Runs against the real tools; counts against the daily agent cap. When no language model is configured, a scripted rule-based planner answers and says so.</span>
        </form>
      )}
    </div>
  )

  return (
    <div className="city">
      <div className="row between" style={{ alignItems: 'flex-start' }}>
        <div><p className="kicker">Funder plan · brief 13</p><h1 style={{ marginBottom: 4 }}>When the line is cut, which critical sites does the budget keep running?</h1></div>
        <SourceBadge src={src} />
      </div>
      <p className="muted" style={{ maxWidth: 820 }}>Each critical site (health facilities, water pumping, market cold rooms) gets its own solar and battery, sized to keep its critical loads running through a 7-day outage at the pessimistic end. The budget funds sites in the city's plan order until it runs out. Ask Wardlight, or set the budget yourself.</p>

      <div className="agent-grid" style={{ marginTop: 16 }}>
        <AgentRun run={run} title="Ask Wardlight" question={chosen?.question ?? (MODE === 'live' ? 'Loading recorded questions…' : 'Recorded sessions need the live API')} controls={controls} />
        <div className="stack">
          <div className="card stack">
            <div className="controls">
              <Segmented id="pcity" label="City" value={city} onChange={(c) => { reset(); setSel(null); setCity(c) }} options={CITIES.map((c) => ({ value: c.id, label: c.name, hint: `${c.state} State` }))} />
              <Segmented id="pdays" label="Line outage" value={days} onChange={(d) => { reset(); setDays(d) }} options={OUTAGE_DAYS.map((d) => ({ value: d, label: `${d} days`, hint: DAY_HINT[d] }))} />
            </div>
            <div className="sector-chips" role="group" aria-label="Sectors to fund">
              {SECTORS.map((x) => <button key={x} type="button" className={`chip pick${sectors.includes(x) ? ' on' : ''}`} aria-pressed={sectors.includes(x)} onClick={() => toggle(x)}><SectorDot sector={x} />{SECTOR_NAME[x]}</button>)}
            </div>
            <div className="field">
              <div className="range-row"><label htmlFor="budget">Budget</label><output htmlFor="budget" className="mono">{naira(budget)}</output></div>
              <input id="budget" type="range" min={0} max={Math.max(maxBudget, STEP)} step={STEP} value={Math.min(budget, Math.max(maxBudget, STEP))} onChange={(e) => { reset(); setBudget(+e.target.value) }} aria-valuetext={naira(budget)} />
              <span className="small muted">N2bn is one month of the gas plant's federal operating support. Funding every site in scope costs {naira(t.capex_every_site_ngn)}.</span>
            </div>
            {sites.loading && !sites.data ? <Loading what={`Loading ${cityInfo.name}`} /> : sites.error && !sites.data ? <Empty>{sites.error.message}</Empty> : (
              <div className="metrics" aria-live="polite">
                <div><div className="kicker">Sites funded</div><div className="counter">{full(t.funded)} <span className="muted">of {full(t.candidates)}</span></div></div>
                <div><div className="kicker">Critical service-hours kept</div><div className="counter"><span className="muted">{share(t.share_today)}</span> → <span className="s-cell">{share(t.share_with_funded)}</span></div><div className="small muted">today, then with the funded sites</div></div>
                <div><div className="kicker">Diesel avoided</div><div className="counter">{full(t.diesel_l_avoided)} L</div><div className="small muted">{t.diesel_ngn_avoided != null ? `${naira(t.diesel_ngn_avoided)} at the May 2026 price` : ''}</div></div>
                <div><div className="kicker">Capex</div><div className="counter">{naira(t.spent_ngn)}</div><div className="small muted">{naira(t.remaining_ngn)} left</div></div>
              </div>
            )}
          </div>
          <CriticalMap sites={mapSites} corridor={cor.data?.data ?? null} selected={sel} onSelect={setSel} reduced={reduced} focus="city" cut
            label={`Map of ${cityInfo.name}'s critical sites during a line cut: lit sites are funded and run on their own solar and battery`} />
          <p className="small muted" style={{ margin: 0 }}>
            Lit: funded, running on its own solar and battery through the cut. Dim: not funded, at what it keeps today.
            {selRow && <> Selected: <Link to={`/site/${encodeURIComponent(selRow.id)}?city=${city}&days=${days}`}>{selRow.name}</Link> ({selRow.funded ? `funded, #${selRow.order} in plan order` : 'not funded'}).</>}
          </p>
        </div>
      </div>

      <section className="block" aria-labelledby="sec-h">
        <div className="block-h"><div><p className="kicker">By sector, {days}-day line cut</p><h2 id="sec-h">What the budget reaches</h2></div></div>
        <div className="table-scroll">
          <table className="table">
            <thead><tr><th>Sector</th><th>Funded</th><th>Kept today</th><th>Kept with the funded sites</th><th>Capex funded</th><th>To fund the rest</th></tr></thead>
            <tbody>{ALL_SECTORS.filter((x) => plan.by_sector[x]).map((x) => { const g = plan.by_sector[x]!; return (
              <tr key={x} className={g.in_scope ? '' : 'muted'}><td><SectorTag sector={x} />{g.in_scope ? '' : ' (not selected)'}</td><td className="mono">{full(g.funded)} of {full(g.sites)}</td><td className="mono">{share(g.share_today)}</td><td className="mono">{share(g.share_with_funded)}</td><td className="mono">{naira(g.capex_funded_ngn)}</td><td className="mono">{naira(g.capex_to_fund_the_rest_ngn)}</td></tr>) })}</tbody>
          </table>
        </div>
        {plan.by_sector.water?.in_scope && plan.water.m3_with > plan.water.m3_today && <p className="small">Water pumped with the funded sites: <span className="mono">{full(plan.water.m3_with)}</span> m³ a day against <span className="mono">{full(plan.water.m3_today)}</span> today, enough for up to <span className="mono">{full(plan.water.people_with_upper)}</span> people at the Sphere minimum of 15 litres a day (an upper count).</p>}
      </section>

      <section className="block" aria-labelledby="watch-h">
        <div className="block-h"><div><p className="kicker">When the line is cut</p><h2 id="watch-h">The watcher reads the cut, then re-plans which sites run first</h2></div></div>
        <LineWatchPanel />
      </section>

      <section className="block" aria-labelledby="list-h">
        <div className="row between">
          <h2 id="list-h" style={{ margin: 0 }}>Plan order, {cityInfo.name}</h2>
          <div className="row no-print">
            <button className="btn small primary" onClick={() => navigate(`/plan/brief?${query}`)}><Icon name="doc" /> Investment brief</button>
            <button className="btn small" onClick={() => download(`wardlight-plan-${city}-${Math.round(budget)}-${days}d.csv`, planCsv(plan, cityInfo.name, m?.data_version))}><Icon name="download" /> CSV</button>
            {MODE === 'live' && <a className="btn small" href={`${BASE}/city/${city}/plan.csv?budget_ngn=${Math.round(budget)}&days=${days}&sectors=${sectors.join(',')}`}><Icon name="download" /> CSV from the API</a>}
            <button className="btn small" onClick={() => window.print()}><Icon name="print" /> PDF</button>
          </div>
        </div>
        <div className="table-scroll" style={{ marginTop: 10 }}>
          <table className="table">
            <thead><tr><th>#</th><th>Site</th><th>System</th><th>Capex</th><th>Critical service-hours kept</th><th>Diesel avoided</th><th>Status</th></tr></thead>
            <tbody>{shown.map((r) => (
              <tr key={r.id} style={funded.has(r.id) ? { background: 'color-mix(in srgb, var(--cell-500) 9%, transparent)' } : undefined}>
                <td className="mono nowrap">{r.order ?? '·'}<div className="small muted">rank {r.rank}</div></td>
                <td><Link to={`/site/${encodeURIComponent(r.id)}?city=${city}&days=${days}`}>{r.name}</Link><div className="small muted"><SectorTag sector={r.sector} />{r.lga ? ` · ${r.lga}` : ''}</div></td>
                <td className="small mono">{r.pv_kwp ?? 'n/a'} kWp, {r.battery_kwh ?? 'n/a'} kWh</td>
                <td className="mono nowrap">{naira(r.capex_ngn)}</td>
                <td className="small"><span className="mono">{full(r.today_h)}</span> today, <span className="mono">{full(r.with_h)}</span> with its system, of <span className="mono">{full(r.needed_h)}</span></td>
                <td className="mono small">{full(r.diesel_l_avoided)} L</td>
                <td>{funded.has(r.id) ? <span className="tag s-cell"><Icon name="check" size={13} />Funded</span> : <span className="tag s-risk"><Icon name="x" size={13} />Waiting</span>}</td>
              </tr>))}</tbody>
          </table>
        </div>
        {plan.rows.length > 15 && <p><button className="btn small" onClick={() => setAll((x) => !x)} aria-expanded={all}>{all ? 'Show the first 15' : `Show all ${full(plan.rows.length)}`}</button></p>}
        <p className="small muted">{PLAN_RULE} Critical service-hours: the hours each critical load is needed in the outage window; "today" is with no backup. Diesel avoided: litres a generator would burn to deliver what each funded system delivers, at N{dieselPrice?.toLocaleString('en-US') ?? 'n/a'} per litre (national average, May 2026). Grid supply is modelled; loads are archetypes. Data version <span className="mono">{m?.data_version ?? 'n/a'}</span>.</p>
      </section>
    </div>
  )
}
