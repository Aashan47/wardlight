import { api } from '../api/client'
import { Loading, RingDivider, TIER, TierTag } from '../components/ui'
import type { Tier } from '../api/types'
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
        <li><strong>Critical loads, by site.</strong> Health sites carry the SEforALL priority-1 loads (delivery room, oxygen, lights) as an archetype, the vaccine fridge on its own PQS system; boreholes a pump sized from the survey's yield and a stated head range; cold rooms a ColdHubs-type room. Archetypes are labelled, not measured per site.</li>
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
      <h2>Matching health facilities to feeders</h2>
      <div className="stack">
        {(Object.keys(TIER) as Tier[]).map((t) => <p key={t} style={{ margin: 0 }}><TierTag tier={t} /> <span className="small">{TIER[t].long}</span></p>)}
      </div>
      <p className="small muted">WHO PQS says of prequalified solar systems: “No additional loads, such as lighting or pumping, are to be connected to the solar power system.” (E003/PV01.3, p. 4). So the vaccine fridge stays on its own PQS system inside each health site, sized and costed apart from the site's other critical loads.</p>

      <RingDivider />
      <h2>Pre-registered results</h2>
      <p className="muted">Targets were written down before any data was parsed, matched or modelled. Misses will be shown next to hits. The agent targets T8 and T9 moved to the brief 13 planner by a dated amendment of 31 October 2026.</p>
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
        <li>Diesel is priced at N3,277.47 per litre, the NBS national average for May 2026 (four outlets report the same figure; the NBS page itself could not be opened). It is a national average, not a Borno pump price; the NBS October 2024 figure, N1,441.28, is kept only as the low end of the range.</li>
        <li>Roof fit rests on OpenStreetMap building outlines; ownership of a roof is not checked. Damaturu has few mapped buildings.</li>
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
      <p className="small muted">Data version <span className="mono">{health.data?.data_version}</span>. The city scoreboard's sources are listed in each metric's evidence drawer.</p>
    </article>
  )
}
