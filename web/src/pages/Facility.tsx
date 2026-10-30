import { useState } from 'react'
import { api, MODE } from '../api/client'
import type { FacilityRecord, Match } from '../api/types'
import { CostCurve } from '../components/charts'
import { FeaturePhone } from '../components/FeaturePhone'
import { NightStage } from '../components/NightStage'
import { CappedNote, ErrorNote, FIX, FixTag, Icon, IntervalBar, Loading, RingDivider, SampleBadge, scenarioOf, TIER, TierTag, VerifiedNote } from '../components/ui'
import { VerifyPanel } from '../agent/VerifyPanel'
import { ngn, num, pct, usd } from '../format'
import { useAsync } from '../hooks'
import { Link } from '../router'

export function FacilityPage({ id }: { id: string }) {
  const { data, error, loading } = useAsync(() => api.facility(id), [id])
  if (loading && !data) return <Loading what="Loading the facility" />
  if (error) return <ErrorNote error={error} />
  if (!data) return null
  const f = data.facility
  return (
    <article>
      <p className="small"><Link to="/">Overview</Link> / <span className="mono">{f.id}</span></p>
      <div className="row between" style={{ alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ marginBottom: 6 }}>{f.name}</h1>
          <p className="muted" style={{ margin: 0 }}>{f.type} · {f.lga === f.state ? f.state : `${f.lga}, ${f.state}`} · <span className="mono">{f.id}</span></p>
        </div>
        <div className="row"><TierTag tier={data.match.tier} />{data.sample && <SampleBadge />}</div>
      </div>
      {MODE === 'fixture' && f.lat === null && <p className="small banner" style={{ marginTop: 12 }}>This record's name and feeder come from the real NERC row below. Its registry match, location and every modelled number are sample data until the matcher and engine run.</p>}
      {data.results_stale && <p className="small banner" style={{ marginTop: 12 }}>This facility's match changed after its figures were computed ({data.result_tier} then, {data.match.tier} now). Precomputed figures use the earlier match until the engine batch is re-run; what-if runs use the current one.</p>}
      {f.source_version && <p className="small muted" style={{ margin: '6px 0 0' }}>Registry: GRID3 {f.source_version.replace('grid3_', '')}{f.code ? <> · SMS code <span className="mono">{f.code}</span></> : null}</p>}

      {data.refused ? <Refused data={data} /> : <Full data={data} />}
    </article>
  )
}

function Refused({ data }: { data: FacilityRecord }) {
  return (
    <section className="card">
      <h2>No supply figure for this facility</h2>
      <p>{data.match.reason}.</p>
      <p className="muted">Wardlight refuses rather than guesses. A refused facility still appears in counts and in the funder plan's list of facilities it could not assess, so the gap is visible.</p>
      <Link to="/method" className="btn">How matching works</Link>
    </section>
  )
}

function Full({ data }: { data: FacilityRecord }) {
  const b = data.brief_metric!, rec = data.recommended!
  const [saved, setSaved] = useState<'idle' | 'saving' | 'saved' | 'failed'>('idle')
  const saveOffline = async () => {
    setSaved('saving')
    try {
      await Promise.all([...api.facilityUrls(data.facility.id), `/facility/${data.facility.id}/sheet`].map((u) => fetch(u)))
      try {
        const list: string[] = JSON.parse(localStorage.getItem('wl-saved') ?? '[]')
        if (!list.includes(data.facility.id)) localStorage.setItem('wl-saved', JSON.stringify([...list, data.facility.id]))
      } catch { /* storage blocked: the cache still holds the sheet */ }
      setSaved('saved')
    } catch { setSaved('failed') }
  }
  return (
    <>
      <section>
        <h2 className="sr-only">Brief 1 metric</h2>
        <div className="metrics">
          <MetricCard label="Days a year the fridge holds 2 to 8 °C, today (household fridge)" v={b.uptime_today} />
          <MetricCard label="With the recommended fix" v={b.uptime_with_system} good />
          <div className="card">
            <div className="kicker">Doses protected a year</div>
            <div className="metric">{num(b.doses_protected_today)}<small> today</small></div>
            <div className="metric s-cell" style={{ fontSize: '1.4rem' }}>{num(b.doses_protected_with_system)}<small> with the fix</small></div>
            {(data.capped ?? data.facility.capped) && <p style={{ margin: '6px 0 0' }}><CappedNote r={data.facility.capped ? data.facility : { ...data.facility, capped: data.capped }} /></p>}
            <p className="small muted" style={{ margin: '6px 0 0' }}>{b.doses_note}.</p>
          </div>
        </div>
      </section>

      {data.fix && data.scenarios && (
        <section className="grid2">
          <div className="card stack">
            <div className="row between"><h3 style={{ margin: 0 }}>Recommended fix</h3><FixTag fix={data.fix.category} /></div>
            <p style={{ margin: 0, fontSize: '1.05rem' }}><strong>{data.fix.label}.</strong> {data.fix.reason}.</p>
            <p className="small muted" style={{ margin: 0 }}>Fix cost <span className="mono">{ngn(data.fix.cost_ngn)}</span>. {data.fix.cost_note}. The three fixes, cheapest first: {Object.values(FIX).map((f) => f.short).join('; ')}.</p>
          </div>
          <div className="card stack">
            <h3 style={{ margin: 0 }}>Today, under each fridge scenario</h3>
            <p className="small muted" style={{ margin: 0 }}>Today's equipment is unknown, so both are shown. Verify by SMS below to narrow it.</p>
            {data.scenarios.map((sc) => (
              <div key={sc.key} className="field">
                <div className="range-row"><span className="small">{sc.headline ? <strong>{sc.label}</strong> : sc.label}</span><span className="mono small">{pct(sc.uptime.p)} <span className="muted">({pct(sc.uptime.lo)} to {pct(sc.uptime.hi)})</span></span></div>
                <IntervalBar v={sc.uptime} label={sc.label} />
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <VerifyPanel id={data.facility.id} name={data.facility.name} />
      </section>

      <section>
        <div className="row between"><h2 style={{ margin: 0 }}>Run the night</h2><span className="small muted">Grid hours from the band; sun and battery from the trace</span></div>
        <p className="muted">Grid blocks switch off, the sun sets, the tank drains and rooms go dark in priority order: fridge first to keep, ward first to drop.</p>
        <NightStage id={data.facility.id} record={data} />
      </section>

      <RingDivider />
      <section style={{ marginTop: 8 }} className="grid2">
        <Evidence match={data.match} name={data.facility.name} />
        <div className="card stack">
          <h3>Survival per load, today</h3>
          <p className="small muted" style={{ marginTop: -6 }}>Share of modelled nights each load keeps power all the hours it needs it (for the vaccine fridge: stays inside 2 to 8 °C, the headline figure), with a 90% interval. {data.sample && <SampleBadge />}</p>
          {data.survival_today!.map((s, i) => (
            <div key={s.load} className="field">
              <div className="range-row"><span className="small">{i + 1}. {s.name}{s.load === 'fridge' ? <span className="muted"> ({scenarioOf(null).replace('if a ', '')})</span> : null}{s.combined ? <span className="muted"> ({s.combined}, one figure)</span> : null}</span><span className="mono small">{pct(s.p)} <span className="muted">({pct(s.lo)} to {pct(s.hi)})</span></span></div>
              <IntervalBar v={s} label={s.name} />
            </div>
          ))}
          {data.supply_model && (
            <p className="small muted" style={{ margin: 0 }}>
              Supply model ({data.supply_model.label}): promised {data.supply_model.promised_hours ?? 'n/a'} h; modelled median {data.supply_model.median_hours ?? 'n/a'} h, 10th percentile {data.supply_model.p10_hours ?? 'n/a'} h. {data.supply_model.note}
            </p>
          )}
        </div>
      </section>

      <section className="grid2">
        <div className="card stack">
          <div className="row between"><h3 style={{ margin: 0 }}>Recommended: two systems, never blurred</h3>{data.sample && <SampleBadge />}</div>
          <div>
            <p className="kicker">1. Cold-chain fix</p>
            <p style={{ margin: 0 }}>{rec.fix?.label ?? rec.fridge_system.design}{rec.fix?.model_name ? <> ({rec.fix.model_name})</> : null}. PQS holdover on the product sheets: {rec.fridge_system.holdover_h_range[0]} to {rec.fridge_system.holdover_h_range[1]} h (to +10 °C, an upper bound for 2 to 8 °C).</p>
            <table className="table" style={{ marginTop: 6 }}>
              <tbody>
                <tr><th scope="row">Capital cost</th><td className="mono">{rec.capex_usd.lo === rec.capex_usd.hi ? usd(rec.capex_usd.mid) : `${usd(rec.capex_usd.lo)} to ${usd(rec.capex_usd.hi)}`}<br /><span className="muted">{rec.capex_ngn.lo === rec.capex_ngn.hi ? ngn(rec.capex_ngn.mid) : `${ngn(rec.capex_ngn.lo)} to ${ngn(rec.capex_ngn.hi)}`}</span></td></tr>
                <tr><th scope="row">Cost a month</th><td className="mono">{ngn(rec.monthly_cost_ngn)}{rec.fix?.monthly_basis ? <span className="muted small"> ({rec.fix.monthly_basis})</span> : null}</td></tr>
              </tbody>
            </table>
            {rec.fix?.price_basis && <p className="small muted" style={{ margin: '4px 0 0' }}>{rec.fix.price_basis}.</p>}
          </div>
          <div>
            <p className="kicker">2. Separate clinic system{MODE === 'live' ? ', optional' : ''}</p>
            <p style={{ margin: 0 }}>{rec.clinic_system.design}: <strong className="mono">{rec.clinic_system.pv_kwp} kWp</strong> PV, <strong className="mono">{rec.clinic_system.battery_kwh} kWh</strong> battery.</p>
            <table className="table" style={{ marginTop: 6 }}>
              <tbody>
                {rec.clinic_line?.capex_ngn && <tr><th scope="row">Capital cost</th><td className="mono">{ngn(rec.clinic_line.capex_ngn.lo)} to {ngn(rec.clinic_line.capex_ngn.hi)}</td></tr>}
                <tr><th scope="row">Diesel it displaces</th><td className="mono">{ngn(rec.monthly_diesel_ngn)} a month</td></tr>
                <tr><th scope="row">Payback</th><td className="mono">{rec.payback_months ? `${rec.payback_months} months` : 'does not pay back on diesel alone'}</td></tr>
                <tr><th scope="row">Diesel avoided</th><td className="mono">{num(rec.diesel_l_avoided)} L a year</td></tr>
                <tr><th scope="row">CO2 avoided</th><td className="mono">{num(rec.co2_kg_avoided)} kg a year <span className="muted">(2.697 kg per litre, EPA)</span></td></tr>
              </tbody>
            </table>
            {data.labels?.diesel && <p className="small muted" style={{ margin: '4px 0 0' }}>Diesel: {data.labels.diesel}.</p>}
          </div>
          <table className="table">
            <tbody>
              <tr><th scope="row">Who pays</th><td>{rec.who_pays.join('; ')}</td></tr>
              <tr><th scope="row">Who maintains</th><td>{rec.maintains}</td></tr>
            </tbody>
          </table>
          <p className="small muted" style={{ margin: 0 }}>Naira at N1,352.37 per USD (CBN central rate).{MODE === 'fixture' ? ' Diesel at N1,441.28 per litre, the newest NBS figure found (October 2024). Generator litres and system prices are sample placeholders.' : ''}</p>
        </div>
        <div className="card stack">
          {data.cost_curve && <><h3>Cost against reliability</h3><CostCurve points={data.cost_curve} chosen={rec.clinic_system.battery_kwh} /></>}
          <h3 style={{ margin: 0 }}>Take it with you</h3>
          <div className="row no-print">
            <Link className="btn" to={`/facility/${data.facility.id}/sheet`}><Icon name="print" /> Printable sheet</Link>
            <button className="btn" onClick={saveOffline} disabled={saved === 'saving'}>
              <Icon name="offline" /> {saved === 'saved' ? 'Saved for offline' : saved === 'saving' ? 'Saving…' : saved === 'failed' ? 'Could not save, retry' : 'Save sheet offline'}
            </button>
          </div>
          <p className="small muted" style={{ margin: 0 }} role="status">{saved === 'saved' ? 'This sheet now opens with no connection, from the installed app or this browser.' : 'Install Wardlight from the browser menu to keep facility sheets on the phone.'}</p>
        </div>
      </section>

      <section className="grid2">
        <FeaturePhone defaultCode={String(data.facility.code ?? data.facility.id.replace(/\D/g, '').replace(/^0+/, ''))} />
        <div className="card">
          <h3>Loads modelled</h3>
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>Priority</th><th>Room</th><th>kW</th><th>When</th></tr></thead>
              <tbody>{data.loads!.map((l) => <tr key={l.key}><td className="mono">{l.priority}</td><td>{l.name}<br /><span className="small muted">{l.source}</span></td><td className="mono">{l.kw}</td><td>{l.hours}</td></tr>)}</tbody>
            </table>
          </div>
        </div>
      </section>
    </>
  )
}

function MetricCard({ label, v, good }: { label: string; v: { p: number; lo: number; hi: number }; good?: boolean }) {
  return (
    <div className="card">
      <div className="kicker">{label}</div>
      <div className={`metric ${good ? 's-cell' : v.p < 0.5 ? 's-risk' : ''}`}>{pct(v.p)}</div>
      <div className="small muted mono">90% interval {pct(v.lo)} to {pct(v.hi)}</div>
      <div style={{ marginTop: 8 }}><IntervalBar v={v} label={label} /></div>
    </div>
  )
}

export function Evidence({ match: m, name }: { match: Match; name: string }) {
  const ev = m.evidence
  return (
    <div className="card stack">
      <h3>Evidence: which feeder, and how we know</h3>
      <div className="row"><TierTag tier={m.tier} /><span className="tag s-sun"><Icon name="q" size={13} />Promised, not measured</span></div>
      <p className="small" style={{ margin: 0 }}>{TIER[m.tier].long} {m.reason}.</p>
      {m.feeder_id && (
        <p style={{ margin: 0 }}>Feeder <Link to={`/feeder/${m.feeder_id}`} className="mono">{m.feeder_name ?? m.feeder_id}</Link>{m.disco ? <> ({m.disco})</> : null}{m.band ? <>, Band <strong>{m.band}</strong></> : null}{m.min_hours !== null && Object.keys(m.bands).length <= 1 ? <>, minimum <strong className="mono">{Math.round(m.min_hours * 10) / 10} h</strong> a day</> : null}</p>
      )}
      {Object.keys(m.bands).length > 1 && <p className="small mono" style={{ margin: 0 }}>Band mixture: {Object.entries(m.bands).map(([k, w]) => `${k} ${pct(w)}`).join(', ')}</p>}
      {ev?.row_text && ev.file ? (
        <>
          <NercRow text={ev.row_text} name={ev.nerc_text ?? name} />
          {ev.crop && <div className="crop-wrap" tabIndex={0} role="region" aria-label="NERC row scan, scroll sideways"><img className="crop" src={ev.crop} alt={`Scan of NERC row ${ev.sn}, page ${ev.page}`} loading="lazy" /></div>}
          <p className="small muted" style={{ margin: 0 }}>{ev.file}, page {ev.page}, row {ev.sn}.{ev.url && <> <a href={ev.url} target="_blank" rel="noopener">Open the NERC order</a>.</>} <VerifiedNote v={ev} />{ev.matched_on && ev.facility_value ? <> Matched on {ev.matched_on.replace('_standard', '')} “{ev.facility_value}”.</> : null}</p>
        </>
      ) : ev?.row_text ? (
        <p className="small" style={{ margin: 0 }}>{ev.row_text}</p>
      ) : ev && MODE === 'fixture' ? (
        <p className="small muted" style={{ margin: 0 }}>Sample record: no NERC row text is attached. The live matcher must quote the exact row it relied on, or the match is refused.</p>
      ) : null}
    </div>
  )
}

/** A NERC row as quoted: "band | feeder | location | minimum hours", with the facility's name marked. */
export function NercRow({ text, name }: { text: string; name: string }) {
  const parts = text.split(' | ')
  const key = name.toUpperCase()
  const mark = (v?: string) => {
    const at = v ? v.toUpperCase().indexOf(key) : -1
    return v && at >= 0 && key.length > 1 ? <>{v.slice(0, at)}<mark>{v.slice(at, at + key.length)}</mark>{v.slice(at + key.length)}</> : v
  }
  // sample rows: "Band C | feeder | location | hours"; NERC September orders: "feeder | station | areas served"
  if (/^Band [A-E]$/.test(parts[0] ?? '')) {
    const [band, feeder, location, hours] = parts
    return <div className="nerc"><dl><dt>Band</dt><dd>{band.replace('Band ', '')}</dd><dt>Feeder</dt><dd>{feeder}</dd><dt>Serving</dt><dd>{mark(location)}</dd><dt>Min. supply</dt><dd>{hours} hours</dd></dl></div>
  }
  const [feeder, station, ...rest] = parts
  return <div className="nerc"><dl><dt>Feeder</dt><dd>{mark(feeder)}</dd>{station && <><dt>Station</dt><dd>{mark(station)}</dd></>}{rest.length > 0 && <><dt>Serving</dt><dd>{mark(rest.join(' | '))}</dd></>}</dl></div>
}
