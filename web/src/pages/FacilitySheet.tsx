import { api, MODE } from '../api/client'
import { smsReply } from '../components/FeaturePhone'
import { ErrorNote, Icon, Loading, SampleBadge, TIER } from '../components/ui'
import { OUTAGE_DAYS } from '../api/brief13'
import { full, share } from '../city/format'
import { hh, ngn, num, pct, usd } from '../format'
import { useAsync } from '../hooks'
import { Link } from '../router'
import { NercRow } from './Facility'

/** One printable page per facility, for a funding request. Precached, so it opens offline. */
export function FacilitySheet({ id }: { id: string }) {
  const { data, error, loading } = useAsync(() => api.facility(id), [id])
  const sms = useAsync(async () => (MODE === 'live' && data?.facility.code ? api.sms(String(data.facility.code)) : null), [data?.facility.code])
  if (loading && !data) return <Loading what="Loading the sheet" />
  if (error) return <ErrorNote error={error} />
  if (!data) return null
  const f = data.facility, m = data.match, b = data.brief_metric, rec = data.recommended, tr = data.trace, o = data.outage
  const firstDark = tr ? tr.rooms.fridge.findIndex((x) => x === false) : -1
  return (
    <div>
      <div className="row no-print" style={{ marginBottom: 14 }}>
        <Link className="btn" to={`/facility/${id}`}>Back to the facility</Link>
        <button className="btn primary" onClick={() => window.print()}><Icon name="print" /> Print or save as PDF</button>
      </div>
      <article className="sheet">
        <div className="row between" style={{ alignItems: 'flex-start' }}>
          <div>
            <p className="kicker" style={{ color: '#565D66' }}>Wardlight facility sheet · <span className="mono">{f.code ? `code ${f.code}` : f.id}</span></p>
            <h1>{f.name}</h1>
            <p className="muted" style={{ marginTop: -4 }}>{f.type}, {f.lga === f.state ? f.state : `${f.lga}, ${f.state}`}</p>
          </div>
          {data.sample && <SampleBadge>Sample data</SampleBadge>}
        </div>

        <h2 style={{ fontSize: '1.1rem', marginTop: 14 }}>When the line is cut: critical service-hours kept</h2>
        {o ? (
          <table className="table">
            <thead><tr><th>Line outage</th><th>Service-hours needed</th><th>Kept today, no backup</th><th>With the outage-ready system</th><th>Diesel avoided</th></tr></thead>
            <tbody>
              {OUTAGE_DAYS.map((d) => o.by_days[String(d)]).filter(Boolean).map((w) => (
                <tr key={w.days}><th scope="row">{w.days} days</th><td className="mono">{full(w.needed_h)}</td><td className="mono">{share(w.share_today)}</td><td className="mono">{w.orfix ? share(w.orfix.share_kept) : 'n/a'}</td><td className="mono">{w.orfix ? `${full(w.orfix.diesel_l_avoided.mid)} L` : 'n/a'}</td></tr>
              ))}
            </tbody>
          </table>
        ) : <p className="small">No outage figures in this record.</p>}
        {o?.outage_ready_fix && <p className="small" style={{ margin: '4px 0 0' }}>Outage-ready system: {o.outage_ready_fix.label}, <span className="mono">{o.outage_ready_fix.pv_kwp} kWp</span> PV, <span className="mono">{o.outage_ready_fix.battery_kwh} kWh</span> battery, capital cost <span className="mono">{ngn(o.outage_ready_fix.capex_ngn.p)}</span> ({ngn(o.outage_ready_fix.capex_ngn.lo)} to {ngn(o.outage_ready_fix.capex_ngn.hi)}). Sized for a {o.outage_ready_fix.days}-day outage; the sun recharges it each day.</p>}

        <h2 style={{ fontSize: '1.1rem', marginTop: 14 }}>On an ordinary day: the vaccine fridge, one critical load</h2>
        {b ? (
          <table className="table">
            <thead><tr><th></th><th>Today (household fridge)</th><th>With the recommended fix</th></tr></thead>
            <tbody>
              <tr><th scope="row">Share of days at 2 to 8 °C</th><td className="mono">{pct(b.uptime_today.p)} ({pct(b.uptime_today.lo)} to {pct(b.uptime_today.hi)})</td><td className="mono">{pct(b.uptime_with_system.p)} ({pct(b.uptime_with_system.lo)} to {pct(b.uptime_with_system.hi)})</td></tr>
            </tbody>
          </table>
        ) : <p>No figure: {m.reason}.</p>}

        <h2 style={{ fontSize: '1.1rem', marginTop: 14 }}>Grid supply evidence</h2>
        <p style={{ margin: '0 0 6px' }}>{TIER[m.tier].label}. {m.feeder_name ? <>Feeder <span className="mono">{m.feeder_name}</span>{m.band ? `, Band ${m.band}` : ''}{m.min_hours !== null ? `, minimum ${Math.round(m.min_hours * 10) / 10} h a day` : ''}. </> : null}Promised hours, never measured.</p>
        {m.evidence?.verified && m.evidence.row_text && <><NercRow text={m.evidence.row_text} name={f.name} /><p className="small muted">{m.evidence.file}, page {m.evidence.page}, row {m.evidence.sn}: {m.evidence.url}</p></>}
        {tr && <p className="small">In the modelled night shown on screen, the fridge {firstDark >= 0 ? `first loses power at ${hh(tr.start_hour + firstDark)}` : 'keeps power all night'}.</p>}

        {rec && (
          <>
            <h2 style={{ fontSize: '1.1rem', marginTop: 14 }}>Recommended systems</h2>
            <table className="table">
              <tbody>
                {data.fix && <tr><th scope="row">Recommended fix</th><td><strong>{data.fix.label}</strong>. {data.fix.reason}. Cost {ngn(data.fix.cost_ngn)}.</td></tr>}
                <tr><th scope="row">Cold chain</th><td>{rec.fridge_system.design}</td></tr>
                <tr><th scope="row">Clinic</th><td className="mono">{rec.clinic_system.pv_kwp} kWp PV, {rec.clinic_system.battery_kwh} kWh battery</td></tr>
                <tr><th scope="row">Capital cost</th><td className="mono">{usd(rec.capex_usd.lo)} to {usd(rec.capex_usd.hi)} ({ngn(rec.capex_ngn.lo)} to {ngn(rec.capex_ngn.hi)})</td></tr>
                <tr><th scope="row">Cost a month vs diesel</th><td className="mono">{ngn(rec.monthly_cost_ngn)} vs {ngn(rec.monthly_diesel_ngn)}</td></tr>
                <tr><th scope="row">Payback</th><td className="mono">{rec.payback_months ? `${rec.payback_months} months` : 'n/a'}</td></tr>
                <tr><th scope="row">Diesel and CO2 avoided</th><td className="mono">{num(rec.diesel_l_avoided)} L, {num(rec.co2_kg_avoided)} kg a year</td></tr>
                <tr><th scope="row">Who pays</th><td>{rec.who_pays.join('; ')}</td></tr>
                <tr><th scope="row">Who maintains</th><td>{rec.maintains}</td></tr>
              </tbody>
            </table>
          </>
        )}

        <h2 style={{ fontSize: '1.1rem', marginTop: 14 }}>By SMS</h2>
        <pre className="mono small" style={{ background: '#ECEAE3', padding: 10, borderRadius: 6, whiteSpace: 'pre-wrap', margin: 0 }}>{sms.data?.reply ?? smsReply(data)}</pre>

        <p className="small muted" style={{ marginTop: 14 }}>
          Sources: NERC feeder orders; GRID3 health facilities (CC BY 4.0); NASA POWER hourly sun; WHO PQS E003; SEforALL Nigeria roadmap (2022); CBN exchange rate; NBS diesel price; EPA emission factor. Full list and licences under How it decides.
          {data.sample && ' Every modelled number on this sheet is sample data from the fixture generator and carries no engine result.'}
        </p>
      </article>
    </div>
  )
}
