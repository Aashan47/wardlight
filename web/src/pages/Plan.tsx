import { useEffect, useMemo, useState } from 'react'
import { api, MODE } from '../api/client'
import type { FixCategory, PlanRow } from '../api/types'
import { AgentRun } from '../agent/AgentRun'
import { useAgentRun } from '../agent/useAgentRun'
import { CappedNote, ErrorNote, FIX, FixTag, Icon, Loading, SampleBadge, scenarioOf, TierTag } from '../components/ui'
import { ngn, num, pct } from '../format'
import { useAsync, useReducedMotion } from '../hooks'
import { FacilityMap } from '../map/FacilityMap'
import type { MapPoint } from '../map/types'
import { Link } from '../router'

const FIXTURE_QUESTION = 'I have N50 million for Edo this year. Protect the most vaccine doses.'
const mix = (a: string, b: string, k: number) => {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
  const [x, y] = [p(a), p(b)]
  return `#${x.map((v, i) => Math.round(v * (1 - k) + y[i] * k).toString(16).padStart(2, '0')).join('')}`
}

export function PlanPage() {
  const reduced = useReducedMotion()
  const summary = useAsync(() => api.summary(), [])
  const recs = useAsync(() => api.recordings(), [])
  const planners = (recs.data?.recordings ?? []).filter((r) => r.agent === 'planner' && r.question)
  const [state, setState] = useState('Edo')
  const plan = useAsync(() => api.plan({ state, target: 0.99 }), [state])
  const max = plan.data?.budget_ngn_max ?? 0
  const [budget, setBudget] = useState<number | null>(null)
  const [all, setAll] = useState(false)
  const [pick, setPick] = useState<string | null>(null)
  const [own, setOwn] = useState('')
  const run = useAgentRun('planner')
  const rows = useMemo(() => plan.data?.ranked ?? [], [plan.data])
  const b = budget ?? Math.round(max * 0.02 / 1e6) * 1e6
  useEffect(() => { if (planners.length && !pick) setPick(planners.find((r) => r.name.includes('kano'))?.name ?? planners[0].name) }, [planners, pick])
  const chosen = planners.find((r) => r.name === pick)
  const question = MODE === 'fixture' ? FIXTURE_QUESTION : chosen?.question ?? 'Loading recorded questions…'

  // the agent drives the page: its rank call sets state and budget; the facilities it ranks pulse; the funded list lights in order
  const s = run.state
  const rankCall = s.tools.find((t) => /rank/.test(t.name))
  const agentState = typeof rankCall?.args.state === 'string' ? rankCall.args.state : undefined
  const agentBudget = Number(rankCall?.args.budget ?? rankCall?.args.budget_ngn ?? s.answer?.totals?.budget_ngn) || undefined
  useEffect(() => { if (agentState) setState(agentState) }, [agentState])
  useEffect(() => { if (agentBudget) setBudget(agentBudget) }, [agentBudget])
  const agentFunded = useMemo(() => {
    const fromAnswer = s.answer?.funded?.map((f) => (typeof f === 'string' ? f : f.unique_id))
    const fromTool = [...s.tools].reverse().find((t) => t.result?.data?.funded)?.result?.data?.funded
    return fromAnswer ?? fromTool
  }, [s.answer, s.tools])
  const considering = useMemo(() => {
    if (s.status !== 'running' || agentFunded) return [] as string[]
    const fromTool = [...s.tools].reverse().find((t) => t.result?.data?.considering)?.result?.data?.considering
    if (fromTool) return fromTool
    return rankCall ? rows.slice(0, 150).map((r) => r.id) : []
  }, [s.status, s.tools, agentFunded, rankCall, rows])
  const [lit, setLit] = useState(0)
  const [pulse, setPulse] = useState(false)
  useEffect(() => { if (!agentFunded) setLit(0) }, [agentFunded])
  useEffect(() => {
    if (!agentFunded) return
    if (reduced) { setLit(agentFunded.length); return }
    if (lit >= agentFunded.length) return
    const step = Math.max(1, Math.ceil(agentFunded.length / 60))
    const h = setTimeout(() => setLit((n) => Math.min(agentFunded.length, n + step)), 35)
    return () => clearTimeout(h)
  }, [agentFunded, lit, reduced])
  useEffect(() => {
    if (reduced || considering.length === 0) return
    const h = setInterval(() => setPulse((p) => !p), 400)
    return () => clearInterval(h)
  }, [reduced, considering.length])

  const agentLit = useMemo(() => new Set(agentFunded?.slice(0, lit) ?? []), [agentFunded, lit])
  const funded = useMemo(() => (agentFunded && s.status !== 'idle' ? agentLit : new Set(rows.filter((r) => r.cumulative_ngn <= b).map((r) => r.id))), [agentFunded, agentLit, rows, b, s.status])
  const consideringSet = useMemo(() => new Set(considering), [considering])
  const fundedRows = rows.filter((r) => funded.has(r.id))
  const doses = fundedRows.reduce((a, r) => a + r.doses_protected_gain, 0)
  const spent = fundedRows.reduce((a, r) => a + r.cost_ngn, 0)
  const byFix = (f: FixCategory) => fundedRows.filter((r) => r.fix === f).length
  const points: MapPoint[] = useMemo(() => rows.filter((r) => r.lat != null && r.lon != null).map((r, n) => {
    const on = funded.has(r.id), thinking = consideringSet.has(r.id) && !on
    const color = FIX[r.fix]?.color ?? '#8A8F98'
    return {
      n, id: r.id, name: r.name, lat: r.lat, lon: r.lon, funded: on,
      color: on ? color : thinking ? (pulse ? '#F0B95E' : mix(color, '#8A8F98', 0.45)) : mix(color, '#8A8F98', 0.7),
      height: (800 + Math.min(r.unmet_hours, 30) * 500) * (thinking && pulse ? 1.35 : on ? 1.15 : 1),
    }
  }), [rows, funded, consideringSet, pulse])

  const go = (body: Record<string, unknown>) => run.start({ path: '/agent/plan', body })
  const controls = (
    <div className="stack">
      {MODE === 'live' && planners.length > 0 && (
        <fieldset style={{ border: 'none', margin: 0, padding: 0 }}>
          <legend className="small" style={{ fontWeight: 500, marginBottom: 6 }}>Recorded sessions</legend>
          <div className="chips">
            {planners.map((r) => (
              <button key={r.name} type="button" className={`chip pick ${pick === r.name ? 'on' : ''}`} aria-pressed={pick === r.name} onClick={() => { run.reset(); setPick(r.name) }} title={r.what}>{r.what}</button>
            ))}
          </div>
        </fieldset>
      )}
      <div className="row">
        <button className="btn primary" disabled={s.status === 'running' || (MODE === 'live' && !chosen)} onClick={() => (MODE === 'fixture' ? run.start({ path: '' }) : go({ question: chosen!.question, recorded: true, recording: chosen!.name }))}>
          <Icon name="play" /> {s.status === 'running' ? 'Running…' : 'Replay this session'}
        </button>
        {s.status !== 'idle' && s.status !== 'running' && <button className="btn" onClick={run.reset}>Clear</button>}
        {MODE === 'live' && s.status === 'done' && s.answer && agentState && <Link className="btn" to={`/plan/brief?state=${encodeURIComponent(agentState)}&budget=${agentBudget ?? ''}`}><Icon name="doc" /> Investment brief for this answer</Link>}
      </div>
      {MODE === 'live' && (
        <form className="field" onSubmit={(e) => { e.preventDefault(); if (own.trim()) go({ question: own.trim() }) }}>
          <label htmlFor="own-q" className="small">Or ask your own question</label>
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            <input id="own-q" type="text" value={own} onChange={(e) => setOwn(e.target.value)} placeholder="N60 million for Bauchi, maternal care first" maxLength={600} />
            <button className="btn" type="submit" disabled={!own.trim() || s.status === 'running'}>Ask</button>
          </div>
          <span className="small muted">Runs against the real tools; counts against the daily agent cap.</span>
        </form>
      )}
    </div>
  )

  if (plan.error && !plan.data) return <ErrorNote error={plan.error} />

  const csv = () => {
    const head = 'rank,id,name,lga,tier,fix,fix_cost_ngn,cumulative_ngn,uptime_today,uptime_with_fix,doses_protected_gain,funded,reason'
    const body = rows.map((r) => [r.rank, r.id, r.name, r.lga, r.tier, r.fix, r.cost_ngn, r.cumulative_ngn, r.uptime_today, r.uptime_with_system, r.doses_protected_gain, funded.has(r.id), r.reason].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','))
    const blob = new Blob([[head, ...body].join('\n')], { type: 'text/csv' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `wardlight-plan-${state.toLowerCase()}-${b}.csv`; a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  }
  const shown = all ? rows : rows.slice(0, 15)
  const states = summary.data?.by_state.map((x) => x.state).filter((x) => x && !/not yet/i.test(x)) ?? [state]

  return (
    <div>
      <div className="row between">
        <div><p className="kicker">Funder plan</p><h1 style={{ marginBottom: 4 }}>Which clinics does the budget reach first?</h1></div>
        {plan.data?.sample && <SampleBadge />}
      </div>
      <p className="muted" style={{ maxWidth: 780 }}>Each clinic gets the cheapest fix that keeps its vaccines at 2 to 8 °C: (i) a PQS ice-lined fridge on the grid it has, (ii) a PQS solar fridge, or (iii) a solar fridge plus the separate clinic system. Facilities are ranked by doses protected per naira of that fix. Ask Wardlight, or drag the budget yourself.</p>

      <div className="agent-grid" style={{ marginTop: 16 }}>
        <AgentRun run={run} title="Ask Wardlight" question={question} controls={controls} />
        <div className="stack">
          <div className="card stack">
            <div className="grid2" style={{ alignItems: 'end' }}>
              <div className="field"><label htmlFor="state">State</label>
                <select id="state" value={state} onChange={(e) => { run.reset(); setBudget(null); setState(e.target.value) }}>{states.map((x) => <option key={x}>{x}</option>)}</select>
              </div>
              <div className="field">
                <div className="range-row"><label htmlFor="budget">Budget</label><output htmlFor="budget" className="mono">{ngn(b)}</output></div>
                <input id="budget" type="range" min={0} max={max || 1} step={Math.max(1e6, Math.round(max / 400 / 1e6) * 1e6)} value={Math.min(b, max || 1)} onChange={(e) => { run.reset(); setBudget(+e.target.value) }} aria-valuetext={ngn(b)} />
              </div>
            </div>
            <div className="metrics" aria-live="polite">
              <div><div className="kicker">Facilities funded</div><div className="counter">{num(fundedRows.length)} <span className="muted">of {num(rows.length)}</span></div></div>
              <div><div className="kicker">Doses protected a year</div><div className="counter s-cell">+{num(doses)}</div></div>
              <div><div className="kicker">Spent</div><div className="counter">{ngn(spent)}</div></div>
            </div>
            <div className="chips">{(Object.keys(FIX) as FixCategory[]).map((f) => <span key={f} className="chip"><span style={{ width: 9, height: 9, borderRadius: 2, background: FIX[f].color, display: 'inline-block' }} />{FIX[f].short}: {num(byFix(f))}</span>)}</div>
          </div>
          {plan.loading && !plan.data ? <Loading what={`Loading ${state}`} /> : <FacilityMap points={points} label={`Budget map for ${state}: columns coloured by fix; faded columns are not yet funded; height is critical load-hours at risk`} legend={<Legend />} />}
        </div>
      </div>

      <section>
        <div className="row between">
          <h2 style={{ margin: 0 }}>Ranked list, {state}</h2>
          <div className="row no-print">
            {MODE === 'live' && <Link className="btn small primary" to={`/plan/brief?state=${encodeURIComponent(state)}&budget=${b}`}><Icon name="doc" /> Investment brief</Link>}
            <button className="btn small" onClick={csv}><Icon name="download" /> CSV</button>
            <button className="btn small" onClick={() => window.print()}><Icon name="print" /> PDF</button>
          </div>
        </div>
        <ol className="plan-cards only-narrow" style={{ marginTop: 10 }} aria-label="Ranked facilities">
          {shown.map((r) => <Card key={r.id} r={r} funded={funded.has(r.id)} />)}
        </ol>
        <div className="table-scroll only-wide" style={{ marginTop: 10 }}>
          <table className="table">
            <thead><tr><th>#</th><th>Facility</th><th>Fix</th><th>Fridge holds 2 to 8 °C</th><th>Fix cost</th><th>Status</th><th className="hide-sm">Why here</th></tr></thead>
            <tbody>{shown.map((r) => <Row key={r.id} r={r} funded={funded.has(r.id)} />)}</tbody>
          </table>
        </div>
        {rows.length > 15 && <p><button className="btn small" onClick={() => setAll((a) => !a)} aria-expanded={all}>{all ? 'Show the top 15' : `Show all ${num(rows.length)}`}</button></p>}
        <p className="small muted">{plan.data?.currency_note}. Ranking: doses protected a year per N1m of the cold-chain fix. "Today" assumes a household or non-PQS fridge. {fundedRows.filter((r) => r.capped).length > 0 && `${num(fundedRows.filter((r) => r.capped).length)} funded facilities have their catchment capped at 20,000 people: their doses are counted at the cap, which is why many show the same figure.`}{plan.data && 'not_ranked' in plan.data ? ' Facilities whose grid supply is unknown are not ranked.' : ''}</p>
      </section>
    </div>
  )
}

function Status({ funded }: { funded: boolean }) {
  return funded ? <span className="tag s-cell"><Icon name="check" size={13} />Funded</span> : <span className="tag s-risk"><Icon name="x" size={13} />Waiting</span>
}

function Row({ r, funded }: { r: PlanRow; funded: boolean }) {
  return (
    <tr style={funded ? { background: 'color-mix(in srgb, var(--cell-500) 9%, transparent)' } : undefined}>
      <td className="mono nowrap">{r.rank}</td>
      <td><Link to={`/facility/${r.id}`}>{r.name}</Link><br /><TierTag tier={r.tier} />{r.capped && <div style={{ marginTop: 4 }}><CappedNote r={r} short /></div>}</td>
      <td>{FIX[r.fix] && <FixTag fix={r.fix} />}</td>
      <td className="small"><span className="mono">{pct(r.uptime_today)}</span> of days today {scenarioOf(r)}; <span className="mono">{pct(r.uptime_with_system)}</span> with the fix</td>
      <td className="mono nowrap">{ngn(r.cost_ngn)}</td>
      <td><Status funded={funded} /></td>
      <td className="small hide-sm">{r.reason}</td>
    </tr>
  )
}

function Card({ r, funded }: { r: PlanRow; funded: boolean }) {
  return (
    <li className={funded ? 'funded' : undefined}>
      <div className="head"><span className="mono">#{r.rank}</span><Link to={`/facility/${r.id}`}><strong>{r.name}</strong></Link></div>
      <div className="chips">
        <span className="chip long">Fridge holds {pct(r.uptime_today)} of days {scenarioOf(r)}, {pct(r.uptime_with_system)} with the fix</span>
        <span className="chip">{ngn(r.cost_ngn)}</span>
        <CappedNote r={r} short />
        {FIX[r.fix] && <FixTag fix={r.fix} />}
        <TierTag tier={r.tier} />
        <Status funded={funded} />
      </div>
      <p className="small muted" style={{ margin: '8px 0 0' }}>{r.reason}</p>
    </li>
  )
}

function Legend() {
  const sw = (c: string) => <span style={{ display: 'inline-block', width: 10, height: 10, background: c, borderRadius: 2, marginRight: 5 }} />
  return (
    <div style={{ display: 'grid', gap: 2 }}>
      {(Object.keys(FIX) as FixCategory[]).map((f) => <div key={f}>{sw(FIX[f].color)}Fix {FIX[f].short}</div>)}
      <div className="muted">faded: not yet funded · height: load-hours at risk</div>
    </div>
  )
}
