import { api } from '../api/client'
import { Loading, RingDivider, TIER, TierTag } from '../components/ui'
import type { Source, Tier } from '../api/types'
import { useAsync } from '../hooks'
import { Link } from '../router'

export function Method() {
  const health = useAsync(() => api.health(), [])
  const results = useAsync(() => api.results(), [])
  return (
    <article style={{ maxWidth: 940 }}>
      <p className="kicker">How it decides</p>
      <h1>From one vulnerable line to a plan for every critical site</h1>
      <ol className="stack" style={{ paddingLeft: 20 }}>
        <li><strong>Critical sites.</strong> Health facilities from the GRID3 registry; motorized and solar boreholes from the iMMAP 2019 survey and the water works from OpenStreetMap; one cold room per named market. The UNIMAID/UMTH solar plant already powers its own site and is left out of every total.</li>
        <li><strong>Critical loads, by site.</strong> Health sites carry the SEforALL priority-1 loads (delivery room, oxygen, lights) as an archetype, the vaccine fridge on its own PQS system; boreholes a pump sized from the survey's yield and a stated head range; cold rooms a ColdHubs-type room. Archetypes are labelled as such; no site was metered.</li>
        <li><strong>Supply before the cut.</strong> The feeder band the regulator promises (A 20, B 16, C 12, D 8, E 4 hours a day) where a site can be matched, modelled below that ceiling and labelled modelled; solar boreholes off the grid.</li>
        <li><strong>The cut.</strong> The grid is forced off for the whole window: 14 days, 40 days (the real 2024 cut, 21 September to 31 October) or 60 days (the brief's two months).</li>
        <li><strong>Sun.</strong> NASA POWER hourly irradiance for each site, across several weather years.</li>
        <li><strong>Sizing.</strong> Each site gets the smallest solar and battery that keeps 95% of its critical hours at the pessimistic end (5th percentile) through a 7-day outage, then runs at every window.</li>
        <li><strong>Critical service-hours.</strong> For every load, the hours it is needed in the window and the hours it is served: today with no backup, today if every site had diesel, and with the plan.</li>
        <li><strong>Plan order and budget.</strong> Sites rank by critical service-hours gained in a 60-day outage, then lower capex. A budget funds sites in that order; one that does not fit is skipped. The <Link to="/plan">Funder plan</Link>, its investment brief and the planner agent all use this one rule.</li>
        <li><strong>Cost per kWh.</strong> Solar and storage over 15 years against diesel (fuel, O&amp;M and the set) and the Maiduguri gas plant's federal operating support. When the plant runs it costs less per kWh; the plan works alongside it and replaces the diesel critical sites burn when the line or the plant fails.</li>
      </ol>

      <RingDivider />
      <h2>Three agents, each checked by code</h2>
      <ul className="stack">
        <li><strong>Planner</strong> (on the <Link to="/plan">Funder plan</Link>): turns a question such as “The line to Maiduguri is cut for two months. I have N2 billion.” into tool calls over the city build, then a costed answer. Every number in the answer must appear in a tool result from the same session, or the answer is blocked; out-of-scope questions, attack forecasts and cities not built are refused.</li>
        <li><strong>Site verifier</strong> (on each site page): asks the officer in charge, the borehole committee or the market association by SMS whether there is a working generator and how long it ran, and turns the model's diesel assumption into reported hours. Sandbox, simulated replies.</li>
        <li><strong>Line watcher</strong> (on the Funder plan): reads TCN's statement that the line is cut, re-plans which sites run first (funded sites on their own solar, then the dark sites in order of critical hours per litre of diesel), and closes the event when the restoration statement arrives. Replayed on the real 2024 cut.</li>
      </ul>

      <RingDivider />
      <h2>The health layer: placing each facility on a feeder</h2>
      <p>Before the line is cut, a health facility's supply is the band its feeder is promised. Wardlight places each GRID3 facility on a feeder from the street lists in NERC's orders, in the tiers below, and refuses where no evidence places it. In the three cities this sets each health site's supply before the cut; during the cut the grid is off. <Link to="/facilities">Health facilities</Link> shows the result for every facility, with its outage hours and its system.</p>
      <div className="stack">
        {(Object.keys(TIER) as Tier[]).map((t) => <p key={t} style={{ margin: 0 }}><TierTag tier={t} /> <span className="small">{TIER[t].long}</span></p>)}
      </div>
      <p className="small muted">WHO PQS says of prequalified solar systems: “No additional loads, such as lighting or pumping, are to be connected to the solar power system.” (E003/PV01.3, p. 4). So the vaccine fridge stays on its own PQS system inside each health site, sized and costed apart from the site's other critical loads.</p>

      <RingDivider />
      <h2>Pre-registered results</h2>
      <p className="muted">Targets were written down before any data was parsed, matched or modelled. Misses are shown next to hits. T1 to T6 test the health-facility layer: the reader, matcher, supply model, sun, sizing and speed. T7 is the vaccine-fridge and dose metric for health sites. T8 and T9 test the planner agent.</p>
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
        <li>A NERC band is a promise. No measured supply exists per site; the shortfall is modelled.</li>
        <li>Critical loads are archetypes. The water works load is an assumption (30 to 300 kW) until the operator confirms it; the existing solar boreholes' array sizes are assumed.</li>
        <li>Diesel is priced at N3,277.47 per litre, the NBS national average for May 2026 (four outlets report the same figure; the NBS page itself could not be opened). It is a national average, so a Borno pump price may differ; the NBS October 2024 figure, N1,441.28, is kept only as the low end of the range.</li>
        <li>Roof fit rests on OpenStreetMap building outlines; ownership of a roof is not checked. Damaturu has few mapped buildings.</li>
        <li>English only. No unreviewed translations.</li>
      </ul>

      <RingDivider />
      <h2>Data and licences</h2>
      {health.loading ? <Loading /> : (
        <div className="table-scroll">
          <table className="table">
            <thead><tr><th>Source</th><th>Licence</th><th>Retrieved</th></tr></thead>
            <tbody>{health.data?.sources.filter((s) => !DOSE_ONLY.test(s.name)).map((s) => <SourceRow key={s.name} s={s} />)}</tbody>
          </table>
        </div>
      )}
      <p className="small muted">The city build also uses OpenStreetMap (ODbL, © OpenStreetMap contributors) for markets, roofs and the 330 kV line, and the iMMAP 2019 Borno water-point survey (CC BY), with every other city source in each metric's evidence drawer.</p>
      {health.data && health.data.sources.some((s) => DOSE_ONLY.test(s.name)) && (
        <details className="small">
          <summary>Sources used only by the vaccine-dose estimate (T7)</summary>
          <p className="muted">The API computes a vaccine-dose estimate for the T7 record. These sources serve only that estimate; no brief 13 figure uses them.</p>
          <div className="table-scroll"><table className="table"><tbody>{health.data.sources.filter((s) => DOSE_ONLY.test(s.name)).map((s) => <SourceRow key={s.name} s={s} />)}</tbody></table></div>
        </details>
      )}
      <p className="small muted">Data version <span className="mono">{health.data?.data_version}</span>.</p>
    </article>
  )
}

/** Sources that serve only the dose estimate (catchment population and birth rate). */
const DOSE_ONLY = /birth rate|WorldPop/i

function SourceRow({ s }: { s: Source }) {
  return <tr><td><a href={s.url} target="_blank" rel="noopener">{s.name}</a></td><td className="small">{s.licence}</td><td className="mono small">{s.retrieved}</td></tr>
}
