// The default route: one city's answer to the brief's five success metrics, with evidence one click away.
import { useEffect, useMemo, useRef, useState } from 'react'
import { b13, MOCK_ALLOWED, weakest } from '../api/brief13-client'
import { CITIES, DEFAULT_DAYS, OUTAGE_DAYS, SECTORS, type CityId, type LabelValue, type Range, type Sector, type SiteProps } from '../api/brief13'
import { Icon } from '../components/ui'
import { useAsync, useReducedMotion } from '../hooks'
import { Link, navigate, useLocation } from '../router'
import { Empty, Segmented, SourceBadge } from '../city/bits'
import { CostChart } from '../city/CostChart'
import { CriticalMap } from '../city/CriticalMap'
import { compact, daysWords, full, labelNote, labelOf, pt, ratio, rv, ROOF, SECTOR_NAME, share, siteResult, span, tw } from '../city/format'
import { LabelChip } from '../city/bits'
import { type MapSite } from '../city/mapdata'
import { OutageNight } from '../city/OutageNight'
import { OwnershipPanel, SectorBars, SectorDot, SectorTag, SitingCard } from '../city/panels'
import { BRIEF, EvidenceDrawer, Tile, type MetricKey, type Others } from '../city/Scoreboard'
import { Guard } from '../city/Guard'

const KEYS: MetricKey[] = ['impact', 'innovation', 'sustainability', 'feasibility', 'scalability']
const DAY_HINT: Record<number, string> = { 14: 'two weeks', 40: 'the 2024 cut', 60: "the brief's two months" }
type View = 'grid' | 'today' | 'plan'

// playback timeline, seconds
const T_CUT = 1.6, T_FLY = 2.4, T_DARK = 3.6, T_PLAN = 6.4, T_END = 10
const ease = (x: number) => (x <= 0 ? 0 : x >= 1 ? 1 : 1 - (1 - x) ** 3)

/** The API's rank when it sends one; otherwise the engine's own /api/city rule: service-hours gained in the outage
    (with minus today), then cost. Sites with their own existing solar (UMTH) are not part of the plan. */
function rankSites<T extends SiteProps>(xs: T[], days: number): T[] {
  const inPlan = xs.filter((s) => !s.existing_onsite && s.planned !== false)
  if (inPlan.some((s) => s.rank != null)) return [...inPlan].sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9) || a.name.localeCompare(b.name))
  const gain = (s: SiteProps) => { const r = siteResult(s, days); return (r.with_h ?? 0) - (r.today_h ?? 0) }
  return [...inPlan].sort((a, b) => gain(b) - gain(a) || (a.system?.capex_ngn ?? 0) - (b.system?.capex_ngn ?? 0) || a.id.localeCompare(b.id))
    .map((s, i) => ({ ...s, rank: i + 1, rank_source: 'rule' as const }))
}

export function CityPage({ city }: { city: CityId }) {
  const { search } = useLocation()
  const qDays = Number(new URLSearchParams(search).get('days'))
  const days = (OUTAGE_DAYS as readonly number[]).includes(qDays) ? qDays : DEFAULT_DAYS
  const cityInfo = CITIES.find((c) => c.id === city)!
  const go = (c: CityId, d: number) => navigate(`${c === 'maiduguri' ? '/' : `/city/${c}`}${d === DEFAULT_DAYS ? '' : `?days=${d}`}`, true, false)

  const met = useAsync(() => b13.metrics(city, days), [city, days])
  const sites = useAsync(() => b13.sites(city), [city])
  const cor = useAsync(() => b13.corridor(), [])
  const oth = useAsync(() => Promise.all(CITIES.map((c) => b13.metrics(c.id, days).then((x) => x.data, () => undefined))), [days])
  const m = met.data?.data
  const others: Others[] = CITIES.map((c, i) => ({ id: c.id, m: oth.data?.[i] }))
  const src = weakest([met.data?.src, sites.data?.src, cor.data?.src])
  const corridor = cor.data?.data ?? null

  const [open, setOpen] = useState<MetricKey | null>(null)
  const [sectors, setSectors] = useState<Set<Sector>>(new Set(SECTORS))
  const [view, setView] = useState<View>('plan')
  const [sel, setSel] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)

  const all = useMemo(() => rankSites((sites.data?.data.features ?? []).map((f) => ({ ...f.properties, _ll: f.geometry.coordinates } as SiteProps & { _ll: number[] })), days), [sites.data, days])
  const rankByRule = all.some((s) => s.rank_source === 'rule')
  const existing = m?.excluded?.existing_onsite ?? []
  const defaultSite = all.find((s) => s.rank != null) ?? all[0]
  // the outage view: top-ranked site of a kind, or the site picked on the map or in the list
  const KINDS = [['health_facility', 'A clinic'], ['solar_borehole', 'A solar borehole'], ['motorized_borehole', 'A motorized borehole'], ['market_cold_room', 'A market cold room']] as const
  const kinds = KINDS.filter(([a]) => all.some((x) => x.archetype === a))
  const [nightKind, setNightKind] = useState<string>('health_facility')
  const nightSite = (sel ? all.find((x) => x.id === sel) : undefined) ?? all.find((x) => x.archetype === nightKind) ?? all[0]
  useEffect(() => { setSel(null); setShowAll(false) }, [city])
  const selId = sel ?? defaultSite?.id ?? null
  const selSite = all.find((s) => s.id === selId)
  const siting = useAsync(() => (selId ? b13.siting(selId).catch(() => null) : Promise.resolve(null)), [selId])

  // ------------------------------------------------------------ the outage, played
  const reduced = useReducedMotion()
  const [playT, setPlayT] = useState<number | null>(null)
  const raf = useRef(0)
  const play = () => {
    cancelAnimationFrame(raf.current)
    const t0 = performance.now()
    let stepAt = 0
    const tick = (now: number) => {
      const s = (now - t0) / 1000
      if (reduced) {
        // stepwise: grid, cut, dark, plan; 1.4 s each, no camera flight
        const marks = [0, T_CUT, T_DARK, T_END - 0.01]
        const k = Math.min(marks.length - 1, Math.floor(s / 1.4))
        if (k !== stepAt || s < 0.05) { stepAt = k; setPlayT(marks[k]) }
      } else setPlayT(Math.min(s, T_END))
      if ((reduced ? s / 1.4 : s) >= (reduced ? 4 : T_END)) { setPlayT(null); setView('plan'); return }
      raf.current = requestAnimationFrame(tick)
    }
    setPlayT(0)
    raf.current = requestAnimationFrame(tick)
  }
  const stop = () => { cancelAnimationFrame(raf.current); setPlayT(null) }
  useEffect(() => () => cancelAnimationFrame(raf.current), [])
  useEffect(() => { stop() }, [city, days]) // eslint-disable-line react-hooks/exhaustive-deps

  const playing = playT !== null
  const phase: View | 'cut' = playing ? (playT! < T_CUT ? 'grid' : playT! < T_DARK ? 'cut' : playT! < T_PLAN ? 'today' : 'plan') : view
  const planned = all.filter((s) => s.planned !== false && s.rank != null)
  const order = new Map(planned.map((s, i) => [s.id, i]))

  const mapSites: MapSite[] = all.filter((s) => sectors.has(s.sector)).map((s) => {
    const r = siteResult(s, days)
    const today = r.share_today ?? 0, withP = r.share_with ?? today
    let glow: number
    if (!playing) glow = view === 'grid' ? 1 : view === 'today' ? today : withP
    else {
      const t = playT!
      if (t < T_FLY) glow = 1
      else if (t < T_PLAN) glow = 1 + (today - 1) * ease((t - T_FLY) / (T_DARK - T_FLY))
      else {
        const i = order.get(s.id)
        const st = i === undefined ? Infinity : T_PLAN + (3 * i) / Math.max(1, planned.length)
        glow = today + (withP - today) * ease((t - st) / 0.5)
      }
    }
    const ll = (s as SiteProps & { _ll: number[] })._ll
    return { id: s.id, name: s.name, sector: s.sector, kw: s.kw ?? 1, lon: ll[0], lat: ll[1], glow, planned: s.planned !== false, rank: s.rank ?? null, today: r.share_today ?? null, withPlan: r.share_with ?? null }
  })
  const dayNow = playing ? Math.min(days, Math.max(0, Math.ceil(((playT! - T_CUT) / (T_PLAN - T_CUT)) * days))) : null

  const shareToday = m ? ratio(m.impact.csh_today, m.impact.csh_needed) : null
  const shareWith = m ? ratio(m.impact.csh_with, m.impact.csh_needed) : null
  const litres = m ? rv(m.impact.diesel_l_avoided) : null
  const caption = !m ? '' : phase === 'grid' ? 'The grid is on. Every critical site draws on the one 330 kV line.'
    : phase === 'cut' ? 'The line is cut. Nothing reaches the city until it is repaired.'
    : phase === 'today' ? `Day ${dayNow ?? days} of ${days}. Today, ${cityInfo.name}'s critical sites keep ${share(shareToday?.point)} of their critical service-hours.`
    : `With the plan, each site runs on its own solar and battery: ${share(shareWith?.point)} of critical service-hours kept, no diesel.`

  const visible = showAll ? all : all.slice(0, 10)
  const toggleSector = (s: Sector) => setSectors((p) => { const n = new Set(p); if (n.has(s) && n.size > 1) n.delete(s); else n.add(s); return n })

  return (
    <div className="city">
      <section id="sec-top" className="hero" aria-labelledby="hero-h">
        <div className="hero-top">
          <p className="kicker">Brief 13 · power for a city the grid can't protect · {cityInfo.name}, {cityInfo.state} State</p>
          <span className="row" style={{ gap: 8 }}><SourceBadge src={src} />{m?.data_version && <span className="small muted mono" title="Engine data version">data {m.data_version}</span>}</span>
        </div>
        {src === 'mock' && <p className="mock-banner" role="note"><b>Mock data.</b> The engine has not served this city yet, so every number on this page is a layout placeholder.</p>}
        {met.error && !m && <Empty>{met.error.message}. {MOCK_ALLOWED ? '' : 'This view appears when the engine serves it.'}</Empty>}
        <h1 id="hero-h" className="hero-h">
          {m && shareToday && shareWith && litres ? (
            <>If the line goes down for {daysWords(days)}, {cityInfo.name}'s critical sites keep <em className="n-today">{share(shareToday.point)}</em> of critical service-hours today and <em className="n-plan">{share(shareWith.point)}</em> with the plan, without burning <em className="n-l">{full(litres.point)}</em> litres of diesel.</>
          ) : <span className="skel" aria-busy="true">{met.loading ? `Running ${cityInfo.name}'s outage…` : ''}</span>}
        </h1>
        <div className="controls">
          <Segmented id="city" label="City" value={city} onChange={(c) => go(c, days)} options={CITIES.map((c) => ({ value: c.id, label: c.name, hint: `${c.state} State` }))} />
          <Segmented id="days" label="Line outage" value={days} onChange={(d) => go(city, d)} options={OUTAGE_DAYS.map((d) => ({ value: d, label: `${d} days`, hint: DAY_HINT[d] }))} />
        </div>
      </section>

      <section className="tiles" aria-label="The brief's five success metrics">
        {m ? KEYS.map((k) => <Guard key={k} what={`The ${BRIEF[k].title} tile`}><Tile k={k} m={m} corridor={corridor} others={others} src={met.data?.src} onOpen={setOpen} /></Guard>)
          : KEYS.map((k) => <article key={k} className={`tile t-${k} skel-tile`} aria-hidden="true"><span className="wpill"><b>{BRIEF[k].title}</b> {BRIEF[k].weight}%</span><p className="brief-words">“{BRIEF[k].words}”</p></article>)}
      </section>

      <section id="sec-map" className="block" aria-labelledby="map-h">
        <div className="block-h">
          <div>
            <p className="kicker">Map of critical loads and the outage risk they face</p>
            <h2 id="map-h">One line feeds the city. The plan puts power inside each site's wall.</h2>
          </div>
        </div>
        <div className="map-tools">
          <button className={`btn ${playing ? '' : 'primary'} play`} onClick={playing ? stop : play} aria-pressed={playing}>
            <Icon name={playing ? 'pause' : 'play'} /> {playing ? 'Stop' : `Run the ${days}-day outage`}
          </button>
          <Segmented id="view" label="Show" value={phase === 'cut' ? 'today' : phase} onChange={(v) => { stop(); setView(v) }}
            options={[{ value: 'grid', label: 'Grid on' }, { value: 'today', label: 'Line cut, today' }, { value: 'plan', label: 'Line cut, with the plan' }]} />
          <div className="sector-chips" role="group" aria-label="Sectors on the map">
            {SECTORS.map((s) => (
              <button key={s} type="button" className={`chip pick${sectors.has(s) ? ' on' : ''}`} aria-pressed={sectors.has(s)} onClick={() => toggleSector(s)}>
                <SectorDot sector={s} />{SECTOR_NAME[s]}
              </button>
            ))}
          </div>
        </div>
        <div className="map-grid">
          <div>
            <CriticalMap sites={mapSites} corridor={corridor} selected={selId} onSelect={setSel} reduced={reduced}
              focus={playing && playT! < T_FLY ? 'corridor' : 'city'} cut={playing ? playT! >= T_CUT : view !== 'grid'}
              label={`Map of ${cityInfo.name}'s critical sites and the 330 kV corridor`} />
            <div className="map-status" aria-live="polite">
              <span className={`phase ph-${phase}`}>{phase === 'grid' ? 'Grid on' : phase === 'cut' ? 'Line cut' : phase === 'today' ? 'Today' : 'With the plan'}</span>
              {dayNow !== null && <span className="daychip mono">day {dayNow} / {days}</span>}
              <span className="cap">{caption}</span>
            </div>
            <MapLegend />
          </div>
          <aside aria-label="Selected site">
            {siting.data ? <Guard what="The siting card"><SitingCard s={siting.data.data} src={siting.data.src} days={days} compactView /></Guard>
              : selSite ? <div className="siting"><p className="kicker">Siting card</p><h3>{selSite.name}</h3><p className="muted small">{siting.loading ? 'Loading the siting card…' : 'The siting card is not available from the API yet.'}</p></div>
              : <Empty>Select a site on the map.</Empty>}
          </aside>
        </div>
      </section>

      {m && (
        <section className="block" aria-labelledby="sec-h">
          <div className="block-h"><div><p className="kicker">Hours of critical service, by sector</p><h2 id="sec-h">What keeps running for {daysWords(days)}</h2></div></div>
          <div className="grid2 wide-left">
            <Guard what="The sector bars"><SectorBars m={m} /></Guard>
            <div className="human">
              {(tw(m.impact.water_m3_per_day_kept).with.point ?? 0) > 0 && <Human v={tw(m.impact.water_m3_per_day_kept).with} before={tw(m.impact.water_m3_per_day_kept).today} unit="m³ of water pumped a day with the plan" />}
              {(tw(m.impact.people_served).with.point ?? 0) > 0 && <Human v={tw(m.impact.people_served).with} before={tw(m.impact.people_served).today} unit={m.impact.people_note ?? 'people that water serves with the plan'} label={m.labels.people_served} />}
              {pt(m.impact.cold_rooms_kept) !== null && <Human v={rv(m.impact.cold_rooms_kept)} unit="market cold rooms kept cold" />}
              {pt(m.sustainability.co2_t_avoided) !== null && <Human v={rv(m.sustainability.co2_t_avoided)} unit={`t of CO₂ not emitted in ${days} days`} />}
            </div>
          </div>
        </section>
      )}

      {m && (
        <section id="sec-cost" className="block" aria-labelledby="cost-h">
          <div className="block-h"><div><p className="kicker">Cost comparison with diesel and the gas plant per kWh delivered</p><h2 id="cost-h">Is it cheaper to run the gas plant, burn diesel, or build local solar?</h2></div></div>
          <Guard what="The cost chart"><CostChart m={m} days={days} /></Guard>
        </section>
      )}

      {m && (
        <section id="sec-own" className="block" aria-labelledby="own-h">
          <div className="block-h"><div><p className="kicker">Funding and ownership model, including community participation</p><h2 id="own-h">Who owns it, who pays, who guards it, who fixes it</h2></div></div>
          <Guard what="The ownership panel"><OwnershipPanel m={m} /></Guard>
        </section>
      )}

      <section id="sec-sites" className="block" aria-labelledby="sites-h">
        <div className="block-h"><div><p className="kicker">Distributed design, ranked</p><h2 id="sites-h">{all.length ? `${full(all.length)} critical sites in ${cityInfo.name}` : `Critical sites in ${cityInfo.name}`}</h2></div></div>
        <ol className="sites">
          {visible.map((s) => {
            const r = siteResult(s, days)
            return (
              <li key={s.id} className={s.id === selId ? 'on' : ''}>
                <button type="button" className="site-row" onClick={() => { setSel(s.id); document.getElementById('sec-map')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' }) }} aria-label={`${s.name}: show on the map and open its siting card`}>
                  <span className="mono rank">{s.rank ?? ''}</span>
                  <span className="nm"><b>{s.name}</b><span className="small muted"><SectorTag sector={s.sector} />{s.archetype ? ` · ${s.archetype}` : ''}{s.kw != null ? ` · ${s.kw} kW critical load` : ''}</span></span>
                  <span className="mono small kept">{share(r.share_today)} <span aria-hidden="true">→</span><span className="sr-only">to</span> <b>{share(r.share_with)}</b></span>
                  <span className="small fitc">{s.siting?.roof_fit ? ROOF[s.siting.roof_fit] : ''}</span>
                </button>
                <Link className="small open" to={`/site/${encodeURIComponent(s.id)}?city=${city}&days=${days}`}>Open</Link>
              </li>
            )
          })}
        </ol>
        {all.length > 10 && <p><button className="btn small" onClick={() => setShowAll((x) => !x)}>{showAll ? 'Show the top 10' : `Show all ${full(all.length)}`}</button></p>}
        <p className="small muted">{rankByRule ? 'Order: service-hours gained in the outage, then cost (the engine\'s rule for the city view).' : 'Order: the API\'s ranking for the plan.'} Kept: share of the site's critical service-hours in a {days}-day outage, today and with the plan.{existing.length > 0 && <> Left out: {existing.map((e) => e.name).join(', ')}, which already {existing.length === 1 ? 'has' : 'have'} on-site solar.</>}</p>
      </section>

      <section id="sec-night" className="block" aria-labelledby="night-h">
        <div className="block-h"><div><p className="kicker">The outage, at one site</p><h2 id="night-h">{nightSite ? `${nightSite.name}, hour by hour through the ${days}-day cut` : 'The outage, at one site'}</h2></div></div>
        <div className="sector-chips" role="group" aria-label="Run the outage at" style={{ marginBottom: 12 }}>
          {kinds.map(([a, label]) => (
            <button key={a} type="button" className={`chip pick${nightSite?.archetype === a ? ' on' : ''}`} aria-pressed={nightSite?.archetype === a} onClick={() => { setSel(null); setNightKind(a) }}>{label}</button>
          ))}
        </div>
        <OutageNight site={nightSite} days={days} />
      </section>

      <section className="block proof" aria-labelledby="proof-h">
        <div className="grid2">
          <div>
            <p className="kicker">Existing proof</p>
            <h2 id="proof-h">The teaching hospital already made its own power</h2>
            <p>The University of Maiduguri Teaching Hospital (UMTH) was building its own solar plant to cut its exposure to grid failures, the brief notes (reference 9), and OpenStreetMap maps a solar plant and a battery plant at the university. It is on the map as existing on-site solar and is not part of this plan. The plan is for the clinics, water points and market cold rooms around it that have none.</p>
          </div>
          <div>
            <p className="kicker">Agents that plan, verify and watch</p>
            <ul className="agent-links">
              <li><Link to="/plan">Funder planner: turns a budget and an outage length into a costed plan, every number checked against the data (on the Funder plan)</Link></li>
              <li><Link to="/site/W-BH-589?city=maiduguri">SMS site verifier: asks a borehole committee, clinic or market by SMS whether a generator runs (on each site page)</Link></li>
              <li><Link to="/plan">Line watcher: reads the line operator's cut and restoration statements and re-plans which sites run first (the 2024 cut, replayed, on the Funder plan)</Link></li>
            </ul>
          </div>
        </div>
      </section>

      <Guard what="The evidence view"><EvidenceDrawer k={open} m={m} corridor={corridor} others={others} src={met.data?.src} onClose={() => setOpen(null)} /></Guard>
    </div>
  )
}

function Human({ v, unit, before, label }: { v: Range; unit: string; before?: Range | null; label?: LabelValue }) {
  return (
    <div className="hum">
      <span className="row between" style={{ gap: 8 }}><b>{full(v.point)}</b>{label && <LabelChip label={labelOf(label)} note={labelNote(label)} />}</span>
      <span>{unit}</span>
      {before && before.point !== null && <small className="muted">today, no backup: {full(before.point)}</small>}
      {!before && span(v, compact) && <small className="muted">range {span(v, compact)}</small>}
    </div>
  )
}

function MapLegend() {
  return (
    <div className="map-legend" aria-label="Map legend">
      <span><span className="lg-lamp" />critical site: brighter = more critical hours kept; size = critical load (health sites share one archetype load; loads are modelled)</span>
      {SECTORS.map((s) => <span key={s}><SectorDot sector={s} />{SECTOR_NAME[s]}</span>)}
      <span><span className="lg-line" />330 kV line, the single point of failure</span>
      <span><span className="lg-plant gas" />MEPP gas plant: gas by road tanker; the plan works alongside it</span>
      <span><span className="lg-plant solar" />UNIMAID/UMTH solar: existing on-site solar, outside our plan</span>
    </div>
  )
}
