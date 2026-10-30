import { useEffect, useMemo, useState } from 'react'
import { api, MODE } from '../api/client'
import type { FacilityListItem, Tier } from '../api/types'
import { FeaturePhone } from '../components/FeaturePhone'
import { Icon, Loading, RingDivider, SampleBadge, scenarioOf, TIER, TierTag, VerifiedNote } from '../components/ui'
import { num, pct } from '../format'
import { useAsync } from '../hooks'
import { FacilityMap } from '../map/FacilityMap'
import { MAP_COLORS, type MapPoint } from '../map/types'
import { Link } from '../router'

const TIER_COLOR: Record<Tier, string> = { a_named: MAP_COLORS.grid, b_place: MAP_COLORS.grid, c_lga_mixture: MAP_COLORS.sun, c_unit_mixture: MAP_COLORS.sun, offgrid: MAP_COLORS.sun, d_refused: MAP_COLORS.unknown }

export function Overview() {
  const summary = useAsync(() => api.summary(), [])
  // the map opens on Kano, the hero's state; the selector stays free
  const [mapState, setMapState] = useState(MODE === 'fixture' ? 'Edo' : 'Kano')
  const all = useAsync(() => api.facilities({ state: mapState }), [mapState])
  // the hero: Bichi General Hospital, named in KEDCO's September 2026 order; looked up by name, never by a hard-coded id
  const featured = useAsync(() => (MODE === 'live' ? api.facilities({ q: 'Bichi General Hospital', limit: 5 }) : Promise.resolve([])), [])
  const feat = featured.data?.find((f) => /^bichi general hospital$/i.test(f.name.trim())) ?? featured.data?.[0]
  const hero = useAsync(() => (feat ? api.facility(feat.id) : Promise.resolve(null)), [feat?.id])
  const ev = hero.data?.match.evidence
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  useEffect(() => { const h = setTimeout(() => setDq(q.trim()), 250); return () => clearTimeout(h) }, [q])
  // search runs on the server across every facility; empty search lists the facilities named in NERC rows
  const search = useAsync(() => (dq ? api.facilities({ q: dq, limit: 8 }) : MODE === 'live' ? api.facilities({ tier: 'a_named', limit: 8 }) : api.facilities({ limit: 8 })), [dq])
  const hits = search.data ?? []
  const points: MapPoint[] = useMemo(() => (all.data ?? []).filter((f) => f.lat !== null && f.lon !== null).map((f, n) => ({
    n, id: f.id, name: f.name, lat: f.lat!, lon: f.lon!, color: TIER_COLOR[f.tier],
    height: f.p_fridge_survives === null ? 1200 : 1200 + (1 - f.p_fridge_survives) * 14000,
  })), [all.data])

  return (
    <div>
      <section style={{ marginTop: 8 }} className="grid2 wide-left">
        <div>
          <p className="kicker">Brief 1 · off-grid cold storage for clinics</p>
          <h1>Will this clinic's vaccine fridge stay at 2 to 8 °C through the night?</h1>
          <p style={{ fontSize: '1.08rem' }}>
            For each Nigerian health facility, Wardlight reads the supply the regulator promises its feeder, models the night that follows,
            and sizes the cheapest solar and battery system that would keep the cold chain cold. Every figure shows its evidence and its uncertainty.
          </p>
          <form role="search" onSubmit={(e) => e.preventDefault()} className="field" style={{ maxWidth: 560 }}>
            <label htmlFor="q">Find a facility</label>
            <div style={{ position: 'relative' }}>
              <input id="q" type="search" placeholder="Name, LGA or code, e.g. WL-0001" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" style={{ paddingLeft: 38 }} />
              <span style={{ position: 'absolute', left: 12, top: 15, color: 'var(--muted)' }}><Icon name="search" /></span>
            </div>
          </form>
          {search.loading && !search.data ? <Loading /> : (
            <ul className="list" aria-label="Matching facilities" style={{ maxWidth: 560, marginTop: 8 }}>
              {hits.map((f) => <FacilityItem key={f.id} f={f} />)}
              {hits.length === 0 && <li className="muted small" style={{ padding: 12 }}>No facility matches “{q}”.</li>}
              {!dq && MODE === 'live' && <li className="small muted" style={{ padding: '8px 4px', borderBottom: 'none' }}>Showing facilities named in a NERC feeder row. Search covers all {num(summary.data?.headline.facilities ?? 0)}.</li>}
            </ul>
          )}
        </div>
        <div className="stack">
          <div className="card">
            <p className="kicker">The promise, in the regulator's own table</p>
            {MODE === 'live' ? (hero.data && ev?.row_text ? (() => {
              const [feeder, station, serving] = ev.row_text.split(' | ')
              const key = (ev.nerc_text ?? hero.data.facility.name).toUpperCase()
              const at = serving ? serving.toUpperCase().indexOf(key) : -1
              const m = hero.data.match
              return (
                <>
                  <div className="nerc" aria-label={`NERC feeder row ${ev.sn}`}>
                    <dl>
                      <dt>Feeder</dt><dd>{feeder}</dd>
                      <dt>Band</dt><dd>{m.band ?? Object.keys(m.bands).join(', ')}</dd>
                      <dt>Station</dt><dd>{station}</dd>
                      <dt>Serving</dt><dd>{at >= 0 ? <>{serving.slice(0, at)}<mark>{serving.slice(at, at + key.length)}</mark>{serving.slice(at + key.length)}</> : serving}</dd>
                      {m.min_hours !== null && Object.keys(m.bands).length <= 1 && <><dt>Min. supply</dt><dd><mark>{m.min_hours}</mark> hours a day</dd></>}
                    </dl>
                  </div>
                  {ev.crop && <div className="crop-wrap" tabIndex={0} role="region" aria-label="NERC row scan, scroll sideways"><img className="crop" src={ev.crop} alt={`Scan of NERC row ${ev.sn} on page ${ev.page} of ${ev.file}`} /></div>}
                  <p className="small muted" style={{ margin: '8px 0 0' }}>
                    NERC, {m.disco} order, page {ev.page}, row {ev.sn}.{ev.url && <> <a href={ev.url} target="_blank" rel="noopener">Source PDF</a>.</>} <VerifiedNote v={ev} />
                    A band is a promise, not a measurement. <Link to={`/facility/${hero.data.facility.id}`}>See {hero.data.facility.name}'s night</Link>.
                  </p>
                </>
              )
            })() : <Loading what="Reading the NERC row" />) : (
              <>
                <div className="nerc" aria-label="NERC feeder row 108">
                  <dl>
                    <dt>Band</dt><dd>C</dd>
                    <dt>Feeder</dt><dd>GOVT. HOUSE</dd>
                    <dt>Serving</dt><dd>HIGH COURT, <mark>NEW GENERAL HOSPITAL</mark>, GRA, NWAWOLOR</dd>
                    <dt>Min. supply</dt><dd><mark>12</mark> hours a day</dd>
                  </dl>
                </div>
                <p className="small muted" style={{ margin: '8px 0 0' }}>
                  NERC, BEDC MYTO order, February 2026, page 14, row 108. <a href="https://nerc.gov.ng/wp-content/uploads/2026/04/BEDC_MYTO_FEB_2026.pdf" target="_blank" rel="noopener">Source PDF</a>.
                  A band is a promise, not a measurement. <Link to="/facility/WL-0001">See this hospital's night</Link>.
                </p>
              </>
            )}
          </div>
          {summary.data?.quotes.slice(0, 2).map((qt) => (
            <blockquote className="quote" key={qt.url}>
              <p>“{qt.text}”</p>
              <cite>{qt.source}. <a href={qt.url} target="_blank" rel="noopener">Source</a></cite>
            </blockquote>
          ))}
        </div>
      </section>

      <RingDivider />
      <section style={{ marginTop: 8 }}>
        <div className="row between">
          <h2 style={{ margin: 0 }}>{mapState} State{MODE === 'fixture' ? ', sample facilities' : ''}</h2>
          {MODE === 'fixture' ? <SampleBadge /> : (
            <label className="row small" style={{ gap: 8 }}>State
              <select value={mapState} onChange={(e) => setMapState(e.target.value)} style={{ width: 'auto', minHeight: 40 }}>
                {(summary.data?.by_state.map((x) => x.state) ?? [mapState]).map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
          )}
        </div>
        <p className="muted">Column height: share of days the vaccine fridge leaves 2 to 8 °C today, {scenarioOf(null)}. Colour: how the facility was placed on the grid. Select a column to open the facility.</p>
        {all.data && <FacilityMap points={points} label={`Map of ${mapState} State facilities as 3D columns`} legend={<TierLegend />} />}
        {MODE === 'live' && summary.data && (
          <div className="metrics" style={{ marginTop: 16 }}>
            <div className="card flat"><div className="kicker">Facilities, all states</div><div className="metric">{num(summary.data.headline.facilities)}</div><p className="small muted" style={{ margin: 0 }}>{(summary.data as { coverage_note?: string }).coverage_note}</p></div>
            <div className="card flat"><div className="kicker">Placed on a feeder</div><div className="metric">{num(summary.data.headline.matched)}</div><p className="small muted" style={{ margin: 0 }}>{num((summary.data.headline as { offgrid?: number }).offgrid ?? 0)} modelled off-grid; {num(summary.data.headline.refused)} refused, each with its reason</p></div>
          </div>
        )}
        {summary.data && (
          <div className="metrics wide-cells" style={{ marginTop: 16 }}>
            {(Object.keys(TIER) as Tier[]).filter((t) => summary.data!.tiers[t] !== undefined).map((t) => (
              <div className="card flat" key={t}>
                <TierTag tier={t} />
                <div className="metric" style={{ marginTop: 8 }}>{num(summary.data!.tiers[t] ?? 0)}<small> facilities</small></div>
                <p className="small muted" style={{ margin: 0 }}>{TIER[t].long}</p>
              </div>
            ))}
          </div>
        )}
        <p className="small" style={{ marginTop: 14 }}>
          <strong>What it cannot see:</strong> measured supply at a facility. NERC bands are promises; the product models the shortfall below them and labels it modelled. Facilities it cannot place on a feeder are refused, counted and listed, never guessed.
        </p>
      </section>

      <RingDivider />
      <section style={{ marginTop: 8 }} className="grid2">
        <div className="stack">
          <h2>For a planner with a budget</h2>
          <p>Rank every facility in a state by fridge-nights saved per naira, drag the budget, and see which clinics it funds, in order, with the reason for each.</p>
          <p><Link className="btn primary" to="/plan">Open the funder plan</Link></p>
          <h2 style={{ marginTop: 24 }}>For the officer in charge</h2>
          <p>Every facility has a one-page sheet that prints, installs and opens offline, and a code that works by SMS on a basic phone.</p>
          <p className="row"><Link className="btn" to={`/facility/${MODE === 'fixture' ? 'WL-0001' : feat?.id ?? ''}/sheet`}><Icon name="doc" /> {MODE === 'fixture' ? 'A sample facility sheet' : 'An example facility sheet'}</Link><Link className="btn" to="/method">How it decides</Link></p>
        </div>
        <FeaturePhone defaultCode={MODE === 'fixture' ? '1' : String(feat?.code ?? '')} />
      </section>
    </div>
  )
}

function FacilityItem({ f }: { f: FacilityListItem }) {
  return (
    <li>
      <Link className="item" to={`/facility/${f.id}`}>
        <span><strong>{f.name}</strong><br /><span className="small muted"><span className="mono">{f.code ?? f.id}</span> · {f.lga}, {f.state}</span></span>
        <span style={{ textAlign: 'right' }}>
          <TierTag tier={f.tier} /><br />
          <span className="small mono">{f.p_fridge_survives === null ? 'no figure' : `fridge holds ${pct(f.p_fridge_survives)} of days ${scenarioOf(f)}`}</span>
        </span>
      </Link>
    </li>
  )
}

function TierLegend() {
  const sw = (c: string) => <span style={{ display: 'inline-block', width: 10, height: 10, background: c, borderRadius: 2, marginRight: 5 }} />
  return <div>{sw(MAP_COLORS.grid)}feeder match &nbsp;{sw(MAP_COLORS.sun)}mixture or off-grid &nbsp;{sw(MAP_COLORS.unknown)}refused</div>
}
