import { useState } from 'react'
import { api, MODE } from '../api/client'
import { Icon } from '../components/ui'
import { useAsync } from '../hooks'
import { Link } from '../router'
import { AgentRun } from './AgentRun'
import type { RunState } from './types'
import { useAgentRun } from './useAgentRun'

const WHO: Record<string, string> = { water: 'the borehole committee', health: 'the officer in charge', cold: 'the market association' }

/** "Verify this site by SMS": turns the site's modelled backup assumption into reported data. Sandbox only. */
export function SiteVerifyPanel({ id, name, sector }: { id: string; name: string; sector: string }) {
  const run = useAgentRun('verifier')
  const recs = useAsync(() => api.recordings(), [])
  const rec = recs.data?.recordings.find((r) => r.agent === 'verifier' && r.site_id)
  const isRecorded = rec?.site_id === id
  const [gen, setGen] = useState('1')
  const [hours, setHours] = useState('')
  const [pump, setPump] = useState('2')
  const s = run.state
  const busy = s.status === 'running'
  const path = `/agent/verify-site/${encodeURIComponent(id)}`
  const replies = [...(sector === 'water' ? [pump] : []), gen, ...(gen === '1' && hours ? [hours] : [])]
  const controls = (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>
        The verifier asks {WHO[sector] ?? 'the site'} what the model can only assume: {sector === 'water' ? 'how the pump is powered, ' : ''}whether there is a working generator, and how long it ran last week. Sandbox, simulated replies: no site is contacted and no SMS is sent.
        {MODE === 'live' && rec && !isRecorded && <> A recorded session exists for <Link to={`/site/${encodeURIComponent(rec.site_id!)}`}>another site</Link>.</>}
      </p>
      {MODE !== 'live' ? <span className="small muted">Needs the live API.</span> : isRecorded ? (
        <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => run.start({ path, body: { recorded: true, recording: rec!.name } })}><Icon name="play" /> {busy ? 'Running…' : 'Replay the recorded session'}</button>
          {s.status !== 'idle' && !busy && <button className="btn" onClick={run.reset}>Clear</button>}
        </div>
      ) : (
        <form className="grid2" style={{ alignItems: 'end' }} onSubmit={(e) => { e.preventDefault(); run.start({ path, body: { replies } }) }}>
          {sector === 'water' && <label className="field small">Typed reply: pump powered by
            <select value={pump} onChange={(e) => setPump(e.target.value)}><option value="1">1 solar</option><option value="2">2 generator</option><option value="3">3 grid</option><option value="4">4 hand pump</option></select></label>}
          <label className="field small">Typed reply: working generator?
            <select value={gen} onChange={(e) => setGen(e.target.value)}><option value="1">1 yes</option><option value="2">2 no</option></select></label>
          {gen === '1' && <label className="field small">Typed reply: hours it ran last week
            <input type="text" inputMode="numeric" value={hours} onChange={(e) => setHours(e.target.value.replace(/[^\d]/g, '').slice(0, 3))} placeholder="0 to 168" /></label>}
          <div className="row"><button className="btn primary" type="submit" disabled={busy}><Icon name="play" /> {busy ? 'Running…' : 'Run with these replies'}</button>{s.status !== 'idle' && !busy && <button className="btn" type="button" onClick={run.reset}>Clear</button>}</div>
        </form>
      )}
    </div>
  )
  return (
    <AgentRun run={run} title="Verify this site by SMS" question={isRecorded && rec?.question ? rec.question : `Verify ${name} by SMS`} badge={`${isRecorded ? 'Recorded session · ' : ''}sandbox, simulated replies`} controls={controls}>
      {(st) => <Conversation s={st} />}
    </AgentRun>
  )
}

function Conversation({ s }: { s: RunState }) {
  const bubbles: { dir: 'out' | 'in'; text: string; key: string }[] = []
  const stages: { lo: number; hi: number; p: number | null; of: number; basis: string }[] = []
  for (const t of s.tools) {
    if (t.name === 'ask_site' && t.args.message) bubbles.push({ dir: 'out', text: String(t.args.message), key: `${t.id}o` })
    if (t.result?.reply) bubbles.push({ dir: 'in', text: t.result.reply, key: `${t.id}i` })
    const iv = t.result?.interval as unknown as { lo: number; hi: number; point: number | null; of: number; basis: string } | undefined
    if (t.name === 'update_site' && iv) stages.push({ lo: iv.lo, hi: iv.hi, p: iv.point, of: iv.of, basis: iv.basis })
  }
  if (!bubbles.length && !stages.length) return null
  const cur = stages[stages.length - 1]
  const pos = (x: number) => (cur && cur.of ? (x / cur.of) * 100 : 0)
  return (
    <div className="grid2" style={{ gap: 14 }}>
      <div className="chat" aria-label="SMS conversation (sandbox, simulated replies)">{bubbles.map((b) => <div key={b.key} className={`bubble ${b.dir}`}>{b.text}</div>)}</div>
      {cur && (
        <div className="stack">
          <strong className="small">Critical service-hours kept in a 7-day line cut, after each reply</strong>
          <div className="narrow" role="img" aria-label={`${cur.lo} to ${cur.hi} of ${cur.of} hours`}>
            <div className="span" style={{ left: `${pos(cur.lo)}%`, width: `${Math.max(1, pos(cur.hi - cur.lo))}%` }} />
            {cur.p !== null && <div className="pt" style={{ left: `${pos(cur.p)}%` }} />}
          </div>
          <ol className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {stages.map((st, i) => <li key={i} className={i === stages.length - 1 ? '' : 'muted'}><span className="mono">{st.p !== null ? `${st.p}` : `${st.lo} to ${st.hi}`} of {st.of}</span> ({st.basis})</li>)}
          </ol>
        </div>
      )}
    </div>
  )
}
