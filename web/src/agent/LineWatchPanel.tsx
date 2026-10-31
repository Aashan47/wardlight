import { MODE } from '../api/client'
import { Icon } from '../components/ui'
import { full, share } from '../city/format'
import { SectorTag } from '../city/panels'
import { Link } from '../router'
import { AgentRun } from './AgentRun'
import type { RunState } from './types'
import { useAgentRun } from './useAgentRun'

const SPEED = 4

interface Signal { id: string; kind: string; at: string; line: string; quote: string; source: string; url?: string }
interface FuelRow { fuel_order: number; id: string; name: string; sector: string; gained_h: number; litres: number; hours_per_litre: number | null }
interface RunOrder { own_solar_count: number; dark_count: number; fuel_first: FuelRow[]; fuel_first_litres: number; litres_to_fuel_every_dark_site: number }

/** "Line watch": reads TCN's line-cut statement, re-plans which sites run first, then closes the event when the line is restored. */
export function LineWatchPanel() {
  const run = useAgentRun('watcher')
  const s = run.state
  const busy = s.status === 'running'
  const controls = (
    <div className="row">
      <button className="btn primary" disabled={busy || MODE !== 'live'} onClick={() => run.start({ path: `/agent/watch-line?recorded=true&speed=${SPEED}`, method: 'GET', speed: SPEED })}>
        <Icon name="play" /> {busy ? 'Running…' : 'Replay the 2024 line cut'}
      </button>
      {s.status !== 'idle' && !busy && <button className="btn" onClick={run.reset}>Clear</button>}
      {MODE !== 'live' && <span className="small muted">Needs the live API.</span>}
    </div>
  )
  return (
    <AgentRun run={run} title="Line watch" askLabel="Task (code only, no model)" question="TCN reports the Gombe to Damaturu to Maiduguri 330 kV line cut. Which critical sites run first, and what did the outage cost?" controls={controls}>
      {(st) => <Watch s={st} />}
    </AgentRun>
  )
}

function Watch({ s }: { s: RunState }) {
  const signals = s.tools.map((t) => (t.result as unknown as { signal?: Signal } | undefined)?.signal).filter(Boolean) as Signal[]
  const ro = ((s.tools.find((t) => t.name === 'replan_run_order')?.result as unknown as { run_order?: RunOrder } | undefined)?.run_order)
  if (!signals.length && !ro) return null
  return (
    <div className="stack">
      {signals.map((g) => (
        <blockquote key={g.id} className={`signal ${g.kind}`} style={{ margin: 0, padding: '8px 12px', borderLeft: `3px solid var(${g.kind === 'cut' ? '--cut' : '--cell-500'})` }}>
          <strong className="small">{g.kind === 'cut' ? 'Line cut' : 'Restored'} · {g.at.slice(0, 16).replace('T', ' ')} WAT</strong>
          <p className="small" style={{ margin: '4px 0' }}>“{g.quote}”</p>
          <span className="small muted">{g.url ? <a href={g.url} target="_blank" rel="noopener">{g.source}</a> : g.source}</span>
        </blockquote>
      ))}
      {ro && (
        <div className="diff" aria-label="Run order during the cut">
          <strong className="small">{full(ro.own_solar_count)} funded sites run on their own solar; {full(ro.dark_count)} go dark unless fuelled. Fuel first, most critical service-hours per litre:</strong>
          {ro.fuel_first.slice(0, 6).map((x, i) => (
            <div key={x.id} className="diff-row" style={{ animationDelay: `${i * 90}ms` }}>
              <div style={{ minWidth: 0 }}><span className="mono">{x.fuel_order}.</span> <Link to={`/site/${encodeURIComponent(x.id)}`}>{x.name}</Link><div className="small muted"><SectorTag sector={x.sector} /></div></div>
              <div className="mono small">{full(x.gained_h)} h for {full(x.litres)} L</div>
            </div>
          ))}
          <span className="small muted">Every dark site together: {full(ro.litres_to_fuel_every_dark_site)} litres for the window.</span>
        </div>
      )}
      {typeof s.answer?.totals?.share_with_plan === 'number' && <span className="small muted">Critical service-hours kept: {share(s.answer.totals.share_today as number)} with nothing built, {share(s.answer.totals.share_with_plan as number)} with the plan.</span>}
    </div>
  )
}
