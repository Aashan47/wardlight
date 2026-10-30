import { api } from '../api/client'
import { Loading, RingDivider, TIER, TierTag } from '../components/ui'
import type { Tier } from '../api/types'
import { useAsync } from '../hooks'
import { WatchPanel } from '../agent/WatchPanel'

export function Method() {
  const health = useAsync(() => api.health(), [])
  const results = useAsync(() => api.results(), [])
  return (
    <article style={{ maxWidth: 940 }}>
      <p className="kicker">How it decides</p>
      <h1>From a regulator's promise to a fridge's night</h1>
      <ol className="stack" style={{ paddingLeft: 20 }}>
        <li><strong>Facility.</strong> Name, type, ward, LGA, state and coordinates from the GRID3 Nigeria health facility registry.</li>
        <li><strong>Feeder match, in four tiers, each with its evidence.</strong> The tier is shown on every screen.</li>
        <li><strong>Grid supply.</strong> The band's minimum hours (A 20, B 16, C 12, D 8, E 4) are the promise. Actual supply is modelled below that ceiling and labelled modelled.</li>
        <li><strong>Sun.</strong> NASA POWER hourly irradiance for the site, across several years.</li>
        <li><strong>Loads, by priority.</strong> Vaccine fridge, delivery room, oxygen, lab, ward. Wattages and hours from the SEforALL Nigeria load table; editable.</li>
        <li><strong>Simulation.</strong> Hourly, across weather years and many grid draws; the battery serves loads in priority order. Output per load: the probability it survives the night, with an interval.</li>
        <li><strong>Sizing.</strong> The cheapest PV and battery that meets the target (default: the fridge survives 99% of nights at the pessimistic end of the interval), with the cost curve and its knee.</li>
        <li><strong>Ranking.</strong> Critical load-hours restored per naira across a state, under a budget.</li>
      </ol>

      <RingDivider />
      <h2>Matching tiers</h2>
      <div className="stack">
        {(Object.keys(TIER) as Tier[]).map((t) => <p key={t} style={{ margin: 0 }}><TierTag tier={t} /> <span className="small">{TIER[t].long}</span></p>)}
      </div>

      <RingDivider />
      <h2>Two systems, never blurred</h2>
      <p>
        WHO PQS says of prequalified solar systems: “No additional loads, such as lighting or pumping, are to be connected to the solar power system.” (E003/PV01.3, p. 4).
        So Wardlight recommends a dedicated PQS solar fridge for the cold chain and a separate clinic system for everything else, sized and costed on its own.
      </p>
      <p>
        PQS holdover is measured until the cabinet reaches +10 °C, not +8 °C, so a holdover figure is an upper bound on time inside 2 to 8 °C. Days are counted against 2 to 8 °C, as brief 1 asks.
      </p>

      <RingDivider />
      <h2>Keeping the data current</h2>
      <p>When NERC publishes a new monthly order, the regulator watcher reads it, compares every feeder's band with the previous order and re-runs the facilities on feeders that changed. Every number it reports is checked against its tool results before it is shown.</p>
      <WatchPanel />
      <RingDivider />
      <h2>Pre-registered results</h2>
      <p className="muted">Targets were written down before any data was parsed, matched or modelled. Misses will be shown next to hits.</p>
      {results.loading ? <Loading /> : (
        <div className="table-scroll">
          <table className="table">
            <thead><tr><th>ID</th><th>What</th><th>Target</th><th>Result</th></tr></thead>
            <tbody>{results.data?.rows.map((r) => (
              <tr key={r.id}><td className="mono">{r.id}</td><td>{r.what}</td><td className="small">{r.target}</td>
                <td>{r.status === 'not_run' ? <span className="tag s-unknown">Not yet run</span> : r.status === 'hit' ? <span className="tag s-cell">Hit</span> : r.status === 'miss' ? <span className="tag s-risk">Miss</span> : <span className="tag s-grid">Reported</span>}{r.result && <div className="small" style={{ marginTop: 4 }}>{r.result}</div>}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}

      <RingDivider />
      <h2>Limits</h2>
      <ul>
        <li>A NERC band is a promise. No measured supply exists per facility; the shortfall is modelled.</li>
        <li>Primary health centres are rarely named in the feeder lists, so many rely on place matches or business-unit mixtures.</li>
        <li>Diesel prices after October 2024 are news-reported only, so diesel costs are shown as labelled ranges.</li>
        <li>The doses figure is an estimate from catchment population, the crude birth rate and an unofficial copy of the national schedule.</li>
        <li>English only. No unreviewed translations.</li>
      </ul>

      <RingDivider />
      <h2>Data and licences</h2>
      {health.loading ? <Loading /> : (
        <div className="table-scroll">
          <table className="table">
            <thead><tr><th>Source</th><th>Licence</th><th>Retrieved</th></tr></thead>
            <tbody>{health.data?.sources.map((s) => <tr key={s.name}><td><a href={s.url} target="_blank" rel="noopener">{s.name}</a></td><td className="small">{s.licence}</td><td className="mono small">{s.retrieved}</td></tr>)}</tbody>
          </table>
        </div>
      )}
      <p className="small muted">Data version <span className="mono">{health.data?.data_version}</span>.</p>
    </article>
  )
}
