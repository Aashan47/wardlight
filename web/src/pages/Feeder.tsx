import { api } from '../api/client'
import { ErrorNote, Loading, SampleBadge, TIER, TierTag, VerifiedNote } from '../components/ui'
import { num } from '../format'
import type { ServedSummary, Tier } from '../api/types'
import { useAsync } from '../hooks'
import { Link } from '../router'

export function FeederPage({ id }: { id: string }) {
  const { data, error, loading } = useAsync(() => api.feeder(id), [id])
  if (loading && !data) return <Loading what="Loading the feeder" />
  if (error) return <ErrorNote error={error} />
  if (!data) return null
  return (
    <article>
      <p className="small"><Link to="/">Overview</Link> / feeder</p>
      <div className="row between">
        <div><p className="kicker">{data.disco} feeder</p><h1 className="mono" style={{ marginBottom: 4 }}>{data.name}</h1></div>
        {data.sample ? <SampleBadge /> : <span className="tag s-cell">Real NERC row</span>}
      </div>
      {data.band && <p>Band <strong>{data.band}</strong>, minimum <strong className="mono">{data.min_hours} h</strong> a day. <span className="tag s-sun">Promised, not measured</span></p>}

      <section className="grid2">
        <div className="card stack">
          <h3>Band history</h3>
          {data.band_history.length ? (
            <div className="table-scroll"><table className="table"><thead><tr><th>Order month</th><th>Band</th><th>Min. hours</th><th>File</th></tr></thead>
              <tbody>{data.band_history.map((h) => <tr key={h.order_month}><td className="mono">{h.order_month}</td><td>{h.band}</td><td className="mono">{h.min_hours}</td><td className="small mono">{h.order_file}</td></tr>)}</tbody></table></div>
          ) : <p className="muted">No band history in this record.</p>}
          {data.history_note && <p className="small muted" style={{ margin: 0 }}>{data.history_note}</p>}
        </div>
        <div className="card stack">
          <h3>NERC rows</h3>
          {data.rows.length ? data.rows.map((r) => (
            <div key={`${r.file}-${r.sn}`} className="stack">
              <div className="nerc"><dl>
                <dt>Band</dt><dd>{r.band}</dd><dt>Feeder</dt><dd>{r.feeder_name}</dd>
                {r.streets ? <><dt>Station</dt><dd>{r.location}</dd><dt>Serving</dt><dd>{r.streets}</dd></> : <><dt>Serving</dt><dd>{r.location}</dd></>}
                <dt>Min. supply</dt><dd>{r.min_hours} hours</dd>
              </dl></div>
              {r.crop && <div className="crop-wrap" tabIndex={0} role="region" aria-label="NERC row scan, scroll sideways"><img className="crop" src={r.crop} alt={`Scan of NERC row ${r.sn}, page ${r.page}`} loading="lazy" /></div>}
              <p className="small muted" style={{ margin: 0 }}>{r.file}, page {r.page}, row {r.sn}. <a href={r.url} target="_blank" rel="noopener">Open the order</a>. <VerifiedNote v={r} /></p>
            </div>
          )) : <p className="muted">No NERC row is attached to this sample feeder.</p>}
        </div>
      </section>

      {data.served_summary && <Served s={data.served_summary} />}

      <section className="card">
        <h3>Facilities matched to this feeder</h3>
        <ul className="list">
          {data.facilities.map((f) => (
            <li key={f.id}><Link className="item" to={`/facility/${f.id}`}><span><strong>{f.name}</strong><br /><span className="small muted">{f.how}</span></span><TierTag tier={f.tier} /></Link></li>
          ))}
          {data.facilities.length === 0 && <li className="muted small" style={{ padding: 12 }}>None.</li>}
        </ul>
      </section>
    </article>
  )
}

function Served({ s }: { s: ServedSummary }) {
  const ctx = s.disco_context
  return (
    <section className="grid2">
      <div className="card stack">
        <h3 style={{ margin: 0 }}>Who depends on this feeder</h3>
        <div className="metrics">
          <div><div className="kicker">Facilities</div><div className="counter">{num(s.facilities)}</div></div>
          <div><div className="kicker">Hospitals</div><div className="counter">{num(s.hospitals)}</div></div>
          <div><div className="kicker">PHCs and clinics</div><div className="counter">{num(s.phcs)}</div></div>
        </div>
        <div className="chips">{(Object.entries(s.by_tier) as [Tier, number][]).map(([t, n]) => <span key={t} className="chip">{TIER[t]?.label ?? t}: {num(n)}</span>)}</div>
        <div className="chips">{Object.entries(s.by_level).map(([l, n]) => <span key={l} className="chip">{l}: {num(n)}</span>)}</div>
        <p className="small muted" style={{ margin: 0 }}>{s.type_rule}.</p>
        <div><div className="kicker">Vaccine doses a year at these facilities</div><div className="counter">{num(s.doses_year)}</div>
          <p className="small muted" style={{ margin: '4px 0 0' }}>{num(s.doses_year_facilities)} facilities with a figure; {num(s.doses_year_shared_with_other_feeders)} of these doses sit at facilities also matched to other feeder rows. {s.doses_note}.</p></div>
      </div>
      <div className="card stack">
        <h3 style={{ margin: 0 }}>Promised against measured hours</h3>
        <div className="metrics">
          <div><div className="kicker">Promised</div><div className="counter">{s.promised_hours ?? 'n/a'} h a day</div></div>
          <div><div className="kicker">Measured, this feeder</div><div className="counter">{s.measured.length ? `${s.measured[0].measured_avg_hours} h` : 'not published'}</div></div>
        </div>
        {s.measured.length > 0 ? (
          <table className="table small"><thead><tr><th>Period</th><th>Measured</th><th>Gap</th><th>NERC action</th></tr></thead>
            <tbody>{s.measured.map((m, i) => <tr key={i}><td>{m.period}</td><td className="mono">{m.measured_avg_hours} h</td><td className="mono">{m.gap_hours} h</td><td>{m.action}</td></tr>)}</tbody></table>
        ) : <p className="small muted" style={{ margin: 0 }}>{s.measured_note}.</p>}
        {ctx && (
          <div className="banner small">
            <strong>{ctx.label}.</strong> Median measured {ctx.median_measured_avg_hours} h against the Band A promise of {ctx.band_a_promise_hours} h (median gap {ctx.median_gap_hours} h), over {num(ctx.failing_band_a_rows_with_measured_hours)} rows. DisCo-wide median, not this feeder.
          </div>
        )}
      </div>
    </section>
  )
}
