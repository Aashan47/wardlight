import type { CityMetrics, DataSource, OwnershipRow, Sector, Siting } from '../api/brief13'
import { Link } from '../router'
import { LabelChip, SourceBadge } from './bits'
import { compact, full, labelNote, labelOf, naira, pt, ratio, ROOF, rv, SECTOR_NAME, SECTOR_SHORT, share, span } from './format'
import { SECTOR_COLOR } from './mapdata'

export function SectorDot({ sector }: { sector: string }) {
  return <span className="sdot" style={{ borderColor: SECTOR_COLOR[sector as Sector] ?? 'var(--muted)' }} aria-hidden="true" />
}
export function SectorTag({ sector }: { sector: string }) {
  return <span className="stag"><SectorDot sector={sector} />{SECTOR_SHORT[sector] ?? sector}</span>
}

// ---------------------------------------------------------------- siting card

const ROOF_CLS: Record<string, string> = { fits: 'ok', partial: 'mid', ground: 'gr', unknown: 'unk' }

export function SitingCard({ s, src, days, compactView }: { s: Siting; src?: DataSource; days?: number; compactView?: boolean }) {
  const need = rv(s.pv_kwp_needed), avail = rv(s.roof_kwp_available), area = rv(s.roof_area_m2), bat = rv(s.battery_kwh), cor = rv(s.corridor_km)
  const fill = need.point && avail.point ? Math.min(1, avail.point / need.point) : null
  const lab = (...ks: string[]) => { const v = ks.map((k) => s.labels?.[k]).find(Boolean); return v ? <LabelChip label={labelOf(v)} note={labelNote(v)} /> : null }
  return (
    <article className="siting" aria-labelledby={`sit-${s.id}`}>
      <header>
        <div className="row between" style={{ alignItems: 'flex-start' }}>
          <div>
            <p className="kicker">Siting card</p>
            <h3 id={`sit-${s.id}`}>{s.name}</h3>
            <p className="small muted" style={{ margin: 0 }}><SectorTag sector={s.sector} />{s.archetype ? <> · {s.archetype}</> : null}{s.lga ? <> · {s.lga}</> : null}</p>
          </div>
          <SourceBadge src={src} />
        </div>
      </header>
      <dl className="sit-rows">
        <div>
          <dt>Roof fit {lab('roof_fit', 'roof')}</dt>
          <dd>
            <span className={`fit ${ROOF_CLS[s.roof_fit] ?? ''}`}>{ROOF[s.roof_fit] ?? s.roof_fit}</span>
            <span className="small muted">PV needed <b className="mono">{need.point === null ? 'n/a' : `${full(need.point)} kWp`}</b>{avail.point !== null && <> · roof holds <b className="mono">{full(avail.point)} kWp</b></>}{area.point !== null && <> on <span className="mono">{full(area.point)} m²</span></>}{s.buildings ? <> across {s.buildings} building{s.buildings === 1 ? '' : 's'}</> : null}</span>
            {fill !== null && <span className="fitbar" role="img" aria-label={`Roof covers ${share(fill)} of the PV needed`}><span style={{ width: `${fill * 100}%` }} /></span>}
            {s.placement && <span className="placement">{s.placement[0].toUpperCase() + s.placement.slice(1)}.</span>}
          </dd>
        </div>
        <div>
          <dt>Battery room {lab('battery', 'security')}</dt>
          <dd><b className="mono">{bat.point === null ? 'n/a' : `${full(bat.point)} kWh`}</b>{span(bat, full) && <span className="small muted"> ({span(bat, full)})</span>}{s.battery_room && <span className="small"> {s.battery_room}</span>}</dd>
        </div>
        <div>
          <dt>New line</dt>
          <dd><b className="mono big">{full(s.new_line_km)} km</b> <span className="small muted">the system sits inside the site's own wall</span></dd>
        </div>
        <div>
          <dt>Distance to the 330 kV line {lab('corridor_km')}</dt>
          <dd><b className="mono">{cor.point === null ? 'n/a' : `${cor.point < 10 ? cor.point.toFixed(1) : full(cor.point)} km`}</b> <span className="small muted">no dependence on it during an outage</span></dd>
        </div>
        {!compactView && (
          <div className="wide">
            <dt>Anti-theft measures {lab('anti_theft', 'security')}</dt>
            <dd>
              <ul className="theft">
                {s.anti_theft.map((a, i) => {
                  const o = typeof a === 'string' ? { measure: a } : a
                  return (
                    <li key={i}>
                      <span>{o.measure}{o.detail && <span className="small muted"> {o.detail}</span>}</span>
                      <span className="row" style={{ gap: 6 }}>
                        {o.label && <LabelChip label={labelOf(o.label)} note={labelNote(o.label)} />}
                        {o.url ? <a className="small" href={o.url} target="_blank" rel="noopener">{o.source ?? 'Source'}</a> : o.source ? <span className="small muted">{o.source}</span> : null}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </dd>
          </div>
        )}
        {s.ownership && (
          <div className="wide">
            <dt>Ownership {s.ownership.label ? <LabelChip label={labelOf(s.ownership.label)} note={labelNote(s.ownership.label)} /> : lab('ownership')}</dt>
            <dd className="own4">
              <span><small>owns</small>{s.ownership.owns}</span><span><small>pays</small>{s.ownership.pays}</span>
              <span><small>guards</small>{s.ownership.guards}</span><span><small>repairs</small>{s.ownership.repairs}</span>
            </dd>
          </div>
        )}
      </dl>
      {!compactView && s.sources && s.sources.length > 0 && (
        <div className="sit-src"><p className="kicker" style={{ margin: '12px 0 6px' }}>Sources</p><ul className="src-list">
          {s.sources.map((x, i) => <li key={i}><span className="src-h">{x.status && <LabelChip label={labelOf(x.status)} />}{x.url ? <a href={x.url} target="_blank" rel="noopener">{x.name}</a> : <span>{x.name}</span>}</span></li>)}
        </ul></div>
      )}
      {compactView && <p style={{ margin: '10px 0 0' }}><Link className="btn small" to={`/site/${encodeURIComponent(s.id)}${s.city ? `?city=${s.city}${days ? `&days=${days}` : ''}` : days ? `?days=${days}` : ''}`}>Full siting card and outage night</Link></p>}
    </article>
  )
}

// ---------------------------------------------------------------- ownership and funding

export function OwnershipPanel({ m }: { m: CityMetrics }) {
  const own = m.sustainability.ownership ?? []
  const fund = m.sustainability.funding ?? []
  const all = m.labels.ownership
  return (
    <div className="ownpanel">
      {all && <p className="row" style={{ gap: 8, margin: 0 }}><LabelChip label={labelOf(all)} note={labelNote(all)} /><span className="small muted">{labelNote(all) ?? ''}</span></p>}
      <div className="own-cards">
        {own.map((o: OwnershipRow, i) => (
          <article key={i} className="own-card">
            <header className="row between"><h3 style={{ margin: 0 }}><SectorDot sector={String(o.sector)} />{SECTOR_NAME[String(o.sector)] ?? o.sector}</h3>{o.label && <LabelChip label={labelOf(o.label)} note={labelNote(o.label)} />}</header>
            {o.model && <p className="small" style={{ margin: '6px 0 10px' }}>{o.model}</p>}
            <dl className="own-grid">
              <dt>Owns</dt><dd>{o.owns}</dd>
              <dt>Pays</dt><dd>{o.pays}</dd>
              <dt>Guards</dt><dd>{o.guards}</dd>
              <dt>Repairs</dt><dd>{o.repairs}</dd>
            </dl>
            {(o.precedent || o.source) && <p className="small muted" style={{ margin: '8px 0 0' }}>{o.precedent}{o.precedent && o.source ? ' ' : ''}{o.url ? <a href={o.url} target="_blank" rel="noopener">{o.source ?? 'Source'}</a> : o.source}</p>}
          </article>
        ))}
        {!own.length && <p className="muted">The API sent no ownership rows for this city.</p>}
      </div>
      {fund.length > 0 && (
        <div className="fund">
          <h3>Funding</h3>
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>Who funds</th><th>What it covers</th><th>Amount</th><th>Terms</th><th>Label</th></tr></thead>
              <tbody>
                {fund.map((f, i) => (
                  <tr key={i}>
                    <td>{f.url ? <a href={f.url} target="_blank" rel="noopener">{f.source}</a> : f.source}</td>
                    <td>{f.covers}</td>
                    <td className="mono nowrap">{pt(f.amount_ngn) === null ? '' : naira(pt(f.amount_ngn))}</td>
                    <td className="small">{f.terms ?? f.note ?? ''}</td>
                    <td>{f.label && <LabelChip label={labelOf(f.label)} note={labelNote(f.label)} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- per-sector service-hours

export function SectorBars({ m }: { m: CityMetrics }) {
  const rows = (Object.entries(m.impact.by_sector) as [Sector, NonNullable<CityMetrics['impact']['by_sector'][Sector]>][])
  const series = [
    { key: 'csh_today' as const, name: 'Today, no backup', cls: 'b-today' },
    { key: 'csh_today_diesel' as const, name: 'Today, with diesel', cls: 'b-diesel' },
    { key: 'csh_with' as const, name: 'With the plan, no diesel', cls: 'b-plan' },
  ]
  return (
    <div className="sbars">
      <ul className="legend" aria-label="Legend">{series.map((s) => <li key={s.key}><span className={`key ${s.cls}`} />{s.name}</li>)}</ul>
      {rows.map(([sec, v]) => (
        <div className="sbar" key={sec}>
          <div className="sbar-h"><SectorDot sector={sec} /><strong>{SECTOR_NAME[sec] ?? sec}</strong>{v.sites != null && <span className="small muted"> {full(v.sites)} sites</span>}<span className="small muted mono" style={{ marginLeft: 'auto' }}>{pt(v.csh_needed) === null ? '' : `${compact(pt(v.csh_needed))} service-hours needed`}</span></div>
          {series.map((s) => {
            const r = ratio(v[s.key], v.csh_needed)
            return (
              <div className="sbar-r" key={s.key}>
                <span className="sr-only">{s.name}</span>
                <span className="track"><span className={`bar ${s.cls}`} style={{ width: `${(r.point ?? 0) * 100}%` }} />{r.lo != null && r.hi != null && r.hi > r.lo && <span className="whisk" style={{ left: `${r.lo * 100}%`, width: `${(r.hi - r.lo) * 100}%` }} />}</span>
                <span className="mono small v">{share(r.point)}</span>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
