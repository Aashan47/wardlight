import { b13 } from '../api/brief13-client'
import { CITIES, DEFAULT_DAYS, OUTAGE_DAYS, type CityId, type SiteProps } from '../api/brief13'
import { ErrorNote, Loading } from '../components/ui'
import { useAsync } from '../hooks'
import { Link, navigate, useLocation } from '../router'
import { LabelChip, Segmented, SourceBadge } from '../city/bits'
import { full, labelNote, labelOf, share, siteResult } from '../city/format'
import { OutageNight } from '../city/OutageNight'
import { SectorTag, SitingCard } from '../city/panels'
import { Guard } from '../city/Guard'
import { SiteVerifyPanel } from '../agent/SiteVerifyPanel'

export function SitePage({ id }: { id: string }) {
  const { search } = useLocation()
  const q = new URLSearchParams(search)
  const qc = q.get('city') as CityId | null
  const qd = Number(q.get('days'))
  const days = (OUTAGE_DAYS as readonly number[]).includes(qd) ? qd : DEFAULT_DAYS
  const guess = qc && CITIES.some((c) => c.id === qc) ? qc : (CITIES.find((c) => id.includes(c.id))?.id ?? 'maiduguri')
  const siting = useAsync(() => b13.siting(id), [id])
  const sites = useAsync(() => b13.sites(guess), [guess])
  const site: SiteProps | undefined = sites.data?.data.features.find((f) => f.properties.id === id)?.properties
  const city = CITIES.find((c) => c.id === guess)!
  const back = `${guess === 'maiduguri' ? '/' : `/city/${guess}`}${days === DEFAULT_DAYS ? '' : `?days=${days}`}`
  const r = site ? siteResult(site, days) : null

  return (
    <article className="city">
      <p className="small"><Link to={back}>{city.name} scoreboard</Link> / <span className="mono">{id}</span></p>
      {siting.loading && !siting.data && <Loading what="Loading the siting card" />}
      {siting.error && <ErrorNote error={siting.error} />}
      {siting.data && (
        <>
          <div className="row between" style={{ alignItems: 'flex-start', marginBottom: 12 }}>
            <div>
              <h1 style={{ marginBottom: 6 }}>{siting.data.data.name}</h1>
              <p className="muted" style={{ margin: 0 }}><SectorTag sector={siting.data.data.sector} /> · {city.name}, {city.state} State</p>
            </div>
            <SourceBadge src={siting.data.src} />
          </div>
          {r && (
            <div className="site-kept">
              <div><span className="kicker">Critical service-hours kept, {days}-day outage</span><b className="mono">{share(r.share_today)} <span aria-hidden="true">→</span><span className="sr-only">today, and with the plan</span> {share(r.share_with)}</b><span className="small muted">today, then with the plan</span></div>
              {r.needed_h != null && <div><span className="kicker">Needed</span><b className="mono">{full(r.needed_h)}</b><span className="small muted">service-hours in the window</span></div>}
              {site?.kw != null && <div><span className="kicker row" style={{ gap: 6 }}>Critical load {site.labels?.kw && <LabelChip label={labelOf(site.labels.kw)} note={labelNote(site.labels.kw)} />}</span><b className="mono">{site.kw} kW{site.kwh_day != null ? `, ${site.kwh_day} kWh a day` : ''}</b><span className="small muted">{site.labels?.kw ? labelNote(site.labels.kw) : site.archetype ?? ''}</span></div>}
            </div>
          )}
          <Segmented id="sd" label="Line outage" value={days} onChange={(d) => navigate(`/site/${encodeURIComponent(id)}?city=${guess}&days=${d}`, true, false)} options={OUTAGE_DAYS.map((d) => ({ value: d, label: `${d} days` }))} />
          <section className="block"><Guard what="The siting card"><SitingCard s={siting.data.data} src={siting.data.src} days={days} /></Guard></section>
          <section className="block" aria-labelledby="sn-h">
            <h2 id="sn-h">The outage night</h2>
            <OutageNight site={site} days={days} />
            {site?.facility_id && <p className="small" style={{ marginTop: 10 }}><Link to={`/facility/${encodeURIComponent(site.facility_id)}`}>This facility's full record and its feeder evidence</Link></p>}
          </section>
          {site && site.rank != null && (
            <section className="block" aria-labelledby="sv-h">
              <h2 id="sv-h">Turn an assumption into reported data</h2>
              <Guard what="The SMS verifier"><SiteVerifyPanel id={id} name={site.name} sector={site.sector} /></Guard>
            </section>
          )}
        </>
      )}
    </article>
  )
}
