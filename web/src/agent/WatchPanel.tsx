import { MODE } from '../api/client'
import { Icon } from '../components/ui'
import { num } from '../format'
import { Link } from '../router'
import { AgentRun } from './AgentRun'
import type { RunState } from './types'
import { useAgentRun } from './useAgentRun'

const HOURS: Record<string, number> = { A: 20, B: 16, C: 12, D: 8, E: 4 } // NERC band minimum hours (06-PRODUCT-DESIGN.md)
const SPEED = 20 // the recorded re-run took about a minute; replayed at 20x

/** "Regulator watch": the watcher diffs feeder bands between two monthly orders; each change animates before to after. */
export function WatchPanel() {
  const run = useAgentRun('watcher')
  const s = run.state
  const busy = s.status === 'running'
  const controls = (
    <div className="row">
      <button className="btn primary" disabled={busy} onClick={() => run.start(MODE === 'fixture' ? { path: '' } : { path: `/agent/watch?recorded=true&speed=${SPEED}`, method: 'GET', speed: SPEED })}>
        <Icon name="play" /> {busy ? 'Running…' : 'Replay the recorded run'}
      </button>
      {s.status !== 'idle' && !busy && <button className="btn" onClick={run.reset}>Clear</button>}
    </div>
  )
  return (
    <AgentRun run={run} title="Regulator watch" question={MODE === 'fixture' ? 'A new BEDC order is out. What changed?' : 'Compare the two latest monthly orders: which feeders changed band, and which facilities does that move?'} askLabel={MODE === 'fixture' ? undefined : 'Task (code only, no model)'} badge={MODE === 'fixture' ? 'Recorded sample · sample feeders' : undefined} controls={controls}>
      {(st) => <Diff s={st} />}
    </AgentRun>
  )
}

interface View { key: string; name: string; sub: string; from: string; to: string; fh: number; th: number; facilities: number; ids: string[]; link?: string }

function Diff({ s }: { s: RunState }) {
  let rows: View[] = []
  const live = s.answer?.changes
  if (live?.length) {
    rows = [...live].sort((a, b) => b.facilities_matched - a.facilities_matched).map((c) => ({
      key: c.feeder_id, name: c.feeder_name, sub: `${c.disco}, ${c.state}`, from: c.band_old, to: c.band_new,
      fh: HOURS[c.band_old] ?? 0, th: HOURS[c.band_new] ?? 0, facilities: c.facilities_matched, ids: [],
    }))
  } else {
    rows = s.tools.flatMap((t) => t.result?.data?.changes ?? []).map((c) => ({
      key: c.feeder_id, name: c.name, sub: 'sample feeder', from: c.from, to: c.to, fh: c.from_hours, th: c.to_hours,
      facilities: Array.isArray(c.facilities) ? c.facilities.length : c.facilities, ids: Array.isArray(c.facilities) ? c.facilities : [], link: `/feeder/${c.feeder_id}`,
    }))
  }
  if (!rows.length) return null
  const top = rows.slice(0, 8)
  return (
    <div className="diff" aria-label="Band changes, before and after">
      <strong className="small">{num(rows.length)} band changes{rows.length > top.length ? `, the ${top.length} touching the most facilities` : ''}</strong>
      {top.map((c, i) => {
        const worse = c.th < c.fh
        return (
          <div key={c.key} className="diff-row" style={{ animationDelay: `${i * 90}ms` }}>
            <div style={{ minWidth: 0 }}>
              {c.link ? <Link to={c.link} className="mono">{c.name}</Link> : <span className="mono">{c.name}</span>}
              <div className="small muted">{c.sub} · {num(c.facilities)} facilities matched{c.ids.length ? <>: {c.ids.map((id, j) => <span key={id}>{j > 0 && ', '}<Link to={`/facility/${id}`}>{id}</Link></span>)}</> : null}</div>
            </div>
            <div className="bands" aria-label={`Band ${c.from}, ${c.fh} hours, to Band ${c.to}, ${c.th} hours`}>
              <span className="band-pill from">{c.from} · {c.fh} h</span>
              <span aria-hidden="true">→</span>
              <span className={`band-pill to ${worse ? '' : 'up'}`} style={{ animationDelay: `${300 + i * 90}ms` }}>{c.to} · {c.th} h</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
