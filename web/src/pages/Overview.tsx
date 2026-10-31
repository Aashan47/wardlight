import { useEffect, useMemo, useState } from 'react'
import { api, MODE } from '../api/client'
import { b13 } from '../api/brief13-client'
import { CITIES, DEFAULT_DAYS, OUTAGE_DAYS, type CityId, type OutageDays, type SiteProps } from '../api/brief13'
import type { FacilityListItem, Tier } from '../api/types'
import { Segmented, SourceBadge } from '../city/bits'
import { daysWords, full, naira, pt, rv, share, siteResult, span } from '../city/format'
import { Icon, Loading, RingDivider, SampleBadge, TIER, TierTag, VerifiedNote } from '../components/ui'
import { num } from '../format'
import { useAsync } from '../hooks'
import { FacilityMap } from '../map/FacilityMap'
import { MAP_COLORS, type MapPoint } from '../map/types'
import { Link } from '../router'
import { NercRow } from './Facility'

/** How a health site's grid supply was placed, from the engine's `supply` text. */
function supplyKind(p: SiteProps): 'feeder' | 'mixture' | 'onsite' {
  if (p.existing_onsite) return 'onsite'
  return /^feeder band/i.test(p.supply ?? '') ? 'feeder' : 'mixture'
}
const KIND_COLOR = { feeder: MAP_COLORS.grid, mixture: MAP_COLORS.sun, onsite: MAP_COLORS.unknown }

/** The health layer of the city plan: every health facility in the city, ranked as the funder plan ranks it. */
export function Overview() {
  const [city, setCity] = useState<CityId>('maiduguri')
  const [days, setDays] = useState<OutageDays>(DEFAULT_DAYS)
  const [all, setAll] = useState(false)
  const c = CITIES.find((x) => x.id === city)!
  const metrics = useAsync(() => b13.metrics(city, days), [city, days])
  const sites = useAsync(() => b13.sites(city), [city])
  const summary = useAsync(() => api.summary(), [])
  const health = useMemo(() => (sites.data?.data.features ?? []).filter((f) => f.properties.sector === 'health'), [sites.data])
  const ranked = useMemo(() => health.map((f) => f.properties).filter((p) => p.rank != null).sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0)), [health])
  const onsite = health.map((f) => f.properties).filter((p) => p.existing_onsite)
  const h = metrics.data?.data.impact.by_sector.health
  const shown = all ? ranked : ranked.slice(0, 10)

  const points: MapPoint[] = useMemo(() => health.filter((f) => f.properties.facility_id).map((f, n) => {
    const r = siteResult(f.properties, days)
    const gained = Math.max(0, (r.with_h ?? 0) - (r.today_h ?? 0))
    return { n, id: f.properties.facility_id!, name: f.properties.name, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], color: KIND_COLOR[supplyKind(f.properties)], height: 1200 + gained * 4 }
  }), [health, days])

  // the evidence card: the city's first-ranked health facility named in a NERC feeder row (live API only)
  const first = ranked.find((p) => supplyKind(p) === 'feeder' && p.facility_id)
  const hero = useAsync(() => (MODE === 'live' && first?.facility_id ? api.facility(first.facility_id) : Promise.resolve(null)), [first?.facility_id])
  const ev = hero.data?.match.evidence

  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 250); return () => clearTimeout(t) }, [q])
  const search = useAsync(() => (dq ? api.facilities({ q: dq, limit: 8 }) : Promise.resolve([] as FacilityListItem[])), [dq])

  return (
    <div>
      <section style={{ marginTop: 8 }}>
        <p className="kicker">Health facilities · the health layer of the city plan</p>
        <h1>Every health facility in the city, and the hours its critical services keep when the line is cut</h1>
        <p style={{ fontSize: '1.08rem', maxWidth: 820 }}>
          For each health facility, Wardlight reads the supply the regulator promises its feeder, forces the grid off for the whole outage,
          and runs it hour by hour: delivery room, oxygen and lights on a solar and battery system sized for a 7-day outage, the vaccine fridge on its own
          prequalified system. The same numbers feed the city scoreboard and the funder plan.
        </p>
        <div className="row" style={{ gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <Segmented id="hf-city" label="City" value={city} onChange={(v) => { setCity(v); setAll(false) }} options={CITIES.map((x) => ({ value: x.id, label: x.name }))} />
          <Segmented id="hf-days" label="Line outage" value={days} onChange={setDays} options={OUTAGE_DAYS.map((d) => ({ value: d, label: `${d} days` }))} />
          <SourceBadge src={metrics.data?.src} />
        </div>
      </section>

      <section>
        {metrics.loading && !metrics.data ? <Loading what="Loading the city figures" /> : h ? (
          <div className="metrics" style={{ marginTop: 16 }}>
            <div className="card flat"><div className="kicker">Health facilities in the plan</div><div className="metric">{num(h.sites ?? ranked.length)}</div>
              <p className="small muted" style={{ margin: 0 }}>{onsite.length ? `${onsite.length} GRID3 rows for UMTH left out: it already runs on its own solar plant` : `${c.name}, ${c.state} State`}</p></div>
            <div className="card flat"><div className="kicker">Critical service-hours kept today</div><div className="metric s-risk">{share(rv(h.csh_today).point != null && pt(h.csh_needed) ? pt(h.csh_today)! / pt(h.csh_needed)! : null)}</div>
              <p className="small muted" style={{ margin: 0 }}>{full(pt(h.csh_today))} of {full(pt(h.csh_needed))} hours, no backup, {daysWords(days)} without the line</p></div>
            <div className="card flat"><div className="kicker">With the plan</div><div className="metric s-cell">{share(pt(h.csh_with) != null && pt(h.csh_needed) ? pt(h.csh_with)! / pt(h.csh_needed)! : null)}</div>
              <p className="small muted" style={{ margin: 0 }}>{full(pt(h.csh_with))} hours, every facility on its own solar and battery</p></div>
            <div className="card flat"><div className="kicker">Diesel avoided, health</div><div className="metric">{full(pt(h.diesel_l_avoided))}<small> L</small></div>
              <p className="small muted" style={{ margin: 0 }}>{span(rv(h.diesel_l_avoided), full) ? <>range {span(rv(h.diesel_l_avoided), full)} L; </> : null}what a generator would burn for the same hours</p></div>
          </div>
        ) : <p className="muted">No health figures for {c.name}.</p>}
      </section>

      <RingDivider />
      <section style={{ marginTop: 8 }}>
        <h2 style={{ marginBottom: 4 }}>{c.name}: health facilities in plan order</h2>
        <p className="muted" style={{ marginTop: 0 }}>Column height: critical service-hours each facility gains with its system in a {days}-day outage. Colour: how its grid supply was placed. Select a column to open the facility.</p>
        {points.length > 0 && <FacilityMap points={points} label={`Map of ${c.name} health facilities as 3D columns`} legend={<KindLegend />} />}
        {sites.loading && !sites.data ? <Loading what="Loading the sites" /> : (
          <>
            <ul className="list" aria-label={`${c.name} health facilities in plan order`} style={{ marginTop: 14 }}>
              {shown.map((p) => <SiteItem key={p.id} p={p} days={days} city={city} />)}
            </ul>
            {ranked.length > 10 && <p><button className="btn" onClick={() => setAll((x) => !x)}>{all ? 'Show the first 10' : `Show all ${num(ranked.length)}`}</button></p>}
            <p className="small muted">Plan order: critical service-hours gained in a 60-day outage, most first; ties by lower capex. The funder plan walks this order until the budget runs out. Critical loads are an archetype (SEforALL Type 2 priority-1 loads); no facility has been metered.</p>
          </>
        )}
      </section>

      <RingDivider />
      <section style={{ marginTop: 8 }} className="grid2 wide-left">
        <div className="stack">
          <h2 style={{ margin: 0 }}>Find any facility in the national registry</h2>
          <p className="muted" style={{ margin: 0 }}>The same engine covers every facility GRID3 lists in Nigeria{MODE === 'live' && summary.data ? `, ${num(summary.data.headline.facilities)} in 37 states` : ''}. Each page shows its feeder evidence, its outage hours and the system that keeps them.</p>
          {MODE === 'fixture' && <p className="small banner" style={{ margin: 0 }}><SampleBadge /> Fixture mode: registry search runs over synthetic sample records (Edo State). They are not engine results.</p>}
          <form role="search" onSubmit={(e) => e.preventDefault()} className="field" style={{ maxWidth: 560 }}>
            <label htmlFor="q">Facility name, LGA or code</label>
            <div style={{ position: 'relative' }}>
              <input id="q" type="search" placeholder="e.g. Gwange, Jere or 8230" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" style={{ paddingLeft: 38 }} />
              <span style={{ position: 'absolute', left: 12, top: 15, color: 'var(--muted)' }}><Icon name="search" /></span>
            </div>
          </form>
          {dq && (search.loading && !search.data ? <Loading /> : (
            <ul className="list" aria-label="Matching facilities" style={{ maxWidth: 560 }}>
              {(search.data ?? []).map((f) => <FacilityItem key={f.id} f={f} />)}
              {(search.data ?? []).length === 0 && <li className="muted small" style={{ padding: 12 }}>No facility matches “{q}”.</li>}
            </ul>
          ))}
        </div>
        <div className="card stack">
          <p className="kicker" style={{ margin: 0 }}>The promise, in the regulator's own table</p>
          {MODE !== 'live' ? <p className="small muted" style={{ margin: 0 }}>The NERC row for a facility is read from the live API.</p>
            : hero.data && ev?.row_text ? (
              <>
                <p style={{ margin: 0 }}><strong>{hero.data.facility.name}</strong>, first in {c.name}'s plan order among facilities named in a feeder row.</p>
                <NercRow text={ev.row_text} name={ev.nerc_text ?? hero.data.facility.name} />
                {ev.crop && <div className="crop-wrap" tabIndex={0} role="region" aria-label="NERC row scan, scroll sideways"><img className="crop" src={ev.crop} alt={`Scan of NERC row ${ev.sn} on page ${ev.page} of ${ev.file}`} /></div>}
                <p className="small muted" style={{ margin: 0 }}>
                  NERC, {hero.data.match.disco} order, page {ev.page}, row {ev.sn}.{ev.url && <> <a href={ev.url} target="_blank" rel="noopener">Source PDF</a>.</>} <VerifiedNote v={ev} />{' '}
                  A band is the regulator's promise of hours, never measured at the facility, and in a line outage it falls to zero. <Link to={`/facility/${hero.data.facility.id}`}>Open {hero.data.facility.name}</Link>.
                </p>
              </>
            ) : first ? <Loading what="Reading the NERC row" /> : <p className="small muted" style={{ margin: 0 }}>No facility in {c.name} is named in a NERC feeder row; their supply is a band mixture for the LGA.</p>}
        </div>
      </section>

      {summary.data && (
        <section>
          <h3>How each facility was placed on the grid, all states</h3>
          <div className="metrics wide-cells">
            {(Object.keys(TIER) as Tier[]).filter((t) => summary.data!.tiers[t] !== undefined).map((t) => (
              <div className="card flat" key={t}>
                <TierTag tier={t} />
                <div className="metric" style={{ marginTop: 8 }}>{num(summary.data!.tiers[t] ?? 0)}<small> facilities</small></div>
                <p className="small muted" style={{ margin: 0 }}>{TIER[t].long}</p>
              </div>
            ))}
          </div>
          <p className="small" style={{ marginTop: 14 }}>
            <strong>What it cannot see:</strong> measured supply at a facility, and its real loads. NERC bands are promises, and in the outage model the grid is off for the whole window. Facilities it cannot place on a feeder are refused, counted and listed, never guessed.
          </p>
        </section>
      )}

      <RingDivider />
      <section style={{ marginTop: 8 }} className="grid2">
        <div className="stack">
          <h2 style={{ margin: 0 }}>For a funder with a fixed budget</h2>
          <p style={{ margin: 0 }}>The funder plan puts these facilities beside the city's water pumping sites and market cold rooms, in one plan order, and shows which ones a budget funds and what the rest would cost.</p>
          <p style={{ margin: 0 }}><Link className="btn primary" to="/plan">Open the funder plan</Link></p>
        </div>
        <div className="stack">
          <h2 style={{ margin: 0 }}>For the officer in charge</h2>
          <p style={{ margin: 0 }}>Every facility has a one-page sheet that prints and opens offline, with its outage hours, the system that keeps them and the feeder evidence.</p>
          <p className="row" style={{ margin: 0 }}>{first?.facility_id && <Link className="btn" to={`/facility/${first.facility_id}/sheet`}><Icon name="doc" /> An example facility sheet</Link>}<Link className="btn" to="/method">How it decides</Link></p>
        </div>
      </section>
    </div>
  )
}

function SiteItem({ p, days, city }: { p: SiteProps; days: number; city: CityId }) {
  const r = siteResult(p, days)
  const to = p.facility_id ? `/facility/${p.facility_id}` : `/site/${p.id}?city=${city}`
  return (
    <li>
      <Link className="item" to={to}>
        <span><strong>{p.name}</strong><br /><span className="small muted"><span className="mono">#{p.rank}</span> · {p.lga ?? ''}{p.system?.pv_kwp != null ? <> · <span className="mono">{p.system.pv_kwp} kWp, {p.system.battery_kwh} kWh</span></> : null}</span></span>
        <span style={{ textAlign: 'right' }} className="small">
          <span className="mono">{share(r.share_today)} to <strong>{share(r.share_with)}</strong></span><br />
          <span className="muted mono">{naira(p.system?.capex_ngn)}</span>
        </span>
      </Link>
    </li>
  )
}

function FacilityItem({ f }: { f: FacilityListItem }) {
  return (
    <li>
      <Link className="item" to={`/facility/${f.id}`}>
        <span><strong>{f.name}</strong><br /><span className="small muted"><span className="mono">{f.code ?? f.id}</span> · {f.lga}, {f.state}</span></span>
        <TierTag tier={f.tier} />
      </Link>
    </li>
  )
}

function KindLegend() {
  const sw = (c: string) => <span style={{ display: 'inline-block', width: 10, height: 10, background: c, borderRadius: 2, marginRight: 5 }} />
  return <div>{sw(KIND_COLOR.feeder)}named in a feeder row &nbsp;{sw(KIND_COLOR.mixture)}band mixture or off-grid &nbsp;{sw(KIND_COLOR.onsite)}own plant, left out of the plan</div>
}
