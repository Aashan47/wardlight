import { api, MODE } from '../api/client'
import type { BriefRow, FixCategory } from '../api/types'
import { CappedNote, ErrorNote, FIX, Icon, Loading, scenarioOf, TIER } from '../components/ui'
import { ngn, num, pct } from '../format'
import { useAsync } from '../hooks'
import { Link, useLocation } from '../router'

/** Investment brief: the funded list with evidence per row, totals, what is not reached, and every assumption. */
export function BriefPage() {
  const { search } = useLocation()
  const q = new URLSearchParams(search)
  const state = q.get('state') ?? 'Edo'
  const budget = q.get('budget') ? Number(q.get('budget')) : undefined
  const metric = q.get('metric') ?? 'doses'
  const params = { state, budget_ngn: budget, metric }
  const { data, error, loading } = useAsync(() => api.brief(params), [state, budget, metric])
  if (MODE === 'fixture') return <div className="card"><h1>Investment brief</h1><p>The brief is built by the API; connect it to export one.</p></div>
  if (loading && !data) return <Loading what="Building the brief" />
  if (error) return <ErrorNote error={error} />
  if (!data) return null
  const t = data.totals
  const capped = data.totals.capped_funded ?? data.funded.filter((r) => r.capped).length
  return (
    <div>
      <div className="row no-print" style={{ marginBottom: 14 }}>
        <Link className="btn" to="/plan">Back to the plan</Link>
        <button className="btn primary" onClick={() => window.print()}><Icon name="print" /> Print or save as PDF</button>
        <a className="btn" href={api.briefCsvUrl(params)} download><Icon name="download" /> CSV, one row per facility</a>
      </div>
      <article className="sheet brief">
        <header className="brief-head">
          <div>
            <p className="kicker" style={{ color: '#565D66', margin: 0 }}>Wardlight investment brief</p>
            <h1 style={{ margin: '4px 0' }}>{data.state}: {ngn(data.budget_ngn)} for the cold chain</h1>
            <p className="muted" style={{ margin: 0 }}>{data.method}.</p>
          </div>
          <p className="small muted mono" style={{ margin: 0, textAlign: 'right' }}>data version {data.data_version}<br />target {pct(data.target)} of days</p>
        </header>

        <section className="brief-totals">
          <div><div className="kicker">Facilities funded</div><div className="metric">{num(t.funded)}</div><div className="small muted">of {num(t.candidates ?? 0)} ranked</div></div>
          <div><div className="kicker">Spent</div><div className="metric">{ngn(t.spent_ngn)}</div><div className="small muted">{ngn(t.left_ngn)} left</div></div>
          <div><div className="kicker">{data.benefit_unit}</div><div className="metric">+{num(t.benefit)}</div>{t.doses_protected_with_fix !== undefined && <div className="small muted">{num(t.doses_protected_today ?? 0)} today, {num(t.doses_protected_with_fix)} with the fixes</div>}</div>
          <div><div className="kicker">Fixes</div><div className="small" style={{ marginTop: 4 }}>{Object.entries(t.fixes ?? {}).map(([k, v]) => <div key={k}>{FIX[k as FixCategory]?.short ?? k}: <span className="mono">{num(v)}</span>{t.spend_by_fix_ngn?.[k] !== undefined && <span className="muted"> ({ngn(t.spend_by_fix_ngn[k])})</span>}</div>)}</div></div>
        </section>
        {capped > 0 && <p className="small banner">{num(capped)} of {num(t.funded)} funded facilities have their catchment capped at 20,000 people: their doses are counted at the cap, which is why many rows show the same figure. The uncapped demand is given on each row.</p>}

        <h2 className="brief-h">Funded, in rank order</h2>
        <ol className="brief-cards only-narrow">{data.funded.map((r) => <Card key={r.id} r={r} />)}</ol>
        <div className="only-wide">
          <table className="table brief-table">
            <thead><tr><th>#</th><th>Facility</th><th>Fix</th><th>Cost</th><th>Cumulative</th><th>Doses gained</th><th>Fridge holds 2 to 8 °C</th><th>Evidence</th></tr></thead>
            <tbody>{data.funded.map((r) => (
              <tr key={r.id}>
                <td className="mono nowrap">{r.rank}</td>
                <td><Link to={`/facility/${r.id}`}>{r.name}</Link><div className="small muted">{r.lga}{r.code ? ` · code ${r.code}` : ''} · {TIER[r.tier]?.label ?? r.tier}</div>{r.capped && <div className="small muted">Catchment capped at 20,000 people{r.doses_demand_uncapped != null ? `; uncapped demand ${num(r.doses_demand_uncapped)} doses a year` : ''}</div>}</td>
                <td className="small">{r.fix_label}{r.fix_model ? <div className="muted">{r.fix_model}</div> : null}</td>
                <td className="mono nowrap">{ngn(r.cost_ngn)}</td>
                <td className="mono nowrap">{ngn(r.cumulative_ngn)}</td>
                <td className="mono nowrap">{num(r.doses_gain ?? r.benefit)}</td>
                <td className="small"><span className="mono">{pct(r.uptime_today)}</span> today {scenarioOf(r)}; <span className="mono">{pct(r.uptime_with_fix)}</span> with the fix</td>
                <td className="small"><Cite r={r} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>

        <h2 className="brief-h">What the budget does not reach</h2>
        <table className="table"><tbody>{data.not_reached.map((n) => (
          <tr key={n.group}><th scope="row" style={{ width: '32%' }}>{n.group}</th><td><span className="mono">{num(n.count)}</span> facilities. {n.why}.{n.cost_ngn_to_fund_all ? <> Funding them all: <span className="mono">{ngn(n.cost_ngn_to_fund_all)}</span>, forgoing <span className="mono">{num(n.benefit_forgone ?? 0)}</span>.</> : null}</td></tr>
        ))}</tbody></table>

        <h2 className="brief-h">Scenarios and labels</h2>
        <ul className="small">{data.scenarios.map((s) => <li key={s.key}>{s.headline && <strong>Headline: </strong>}{s.text}</li>)}{Object.entries(data.labels).map(([k, v]) => <li key={k}><strong>{k}:</strong> {v}</li>)}</ul>
        {data.staleness?.note && <p className="small banner">{data.staleness.note}</p>}

        <h2 className="brief-h">Assumptions (every engine constant not taken from a source)</h2>
        <div className="table-scroll"><table className="table small">
          <thead><tr><th>Constant</th><th>Value</th><th>Range</th><th>Status</th><th>Source</th></tr></thead>
          <tbody>{data.assumptions.map((a) => <tr key={a.name}><td className="mono">{a.name}</td><td className="mono nowrap">{String(a.value)}{a.unit ? ` ${a.unit}` : ''}</td><td className="mono nowrap">{a.lo !== undefined ? `${a.lo} to ${a.hi}` : ''}</td><td><span className={`tag ${a.status === 'UNVERIFIED' ? 's-risk' : 's-sun'}`}>{a.status}</span></td><td>{a.source}</td></tr>)}</tbody>
        </table></div>

        <h2 className="brief-h">Sources</h2>
        <ul className="small">{data.sources.map((s) => <li key={s.name}>{s.name}. {s.licence}. <span className="muted">{s.url}</span></li>)}</ul>
        <p className="small muted">{data.currency_note}. Grid supply is modelled from NERC's band promise: promised, not measured. Doses are estimates.</p>
      </article>
    </div>
  )
}

function Cite({ r }: { r: BriefRow }) {
  const c = r.citation
  if (c.kind === 'nerc_row' && c.file) return <>{c.row_text}<div className="muted">{c.url ? <a href={c.url} target="_blank" rel="noopener">{c.file}</a> : c.file}, p. {c.page}, row {c.sn}. {c.verified ? `Checked by eye${c.checked_by ? ` by ${c.checked_by}` : ''}${c.how ? `, ${c.how}` : ''}.` : 'Read by OCR, not checked by eye.'}</div></>
  return <>{c.text}</>
}

function Card({ r }: { r: BriefRow }) {
  return (
    <li>
      <div className="head"><span className="mono">#{r.rank}</span><Link to={`/facility/${r.id}`}><strong>{r.name}</strong></Link></div>
      <div className="chips">
        <span className="chip">{ngn(r.cost_ngn)}</span>
        <span className="chip">+{num(r.doses_gain ?? r.benefit)} doses</span>
        <span className="chip long">{pct(r.uptime_today)} of days {scenarioOf(r)}, {pct(r.uptime_with_fix)} with the fix</span>
        <CappedNote r={r} short />
      </div>
      <p className="small" style={{ margin: '6px 0 0' }}>{r.fix_label}{r.fix_model ? ` (${r.fix_model})` : ''}. {r.lga}.</p>
      <p className="small muted" style={{ margin: '4px 0 0' }}><Cite r={r} /></p>
    </li>
  )
}
