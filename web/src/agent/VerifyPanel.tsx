import { useState } from 'react'
import { api, MODE } from '../api/client'
import { Icon } from '../components/ui'
import { pctFine as pct } from '../format'
import { useAsync } from '../hooks'
import { Link } from '../router'
import { AgentRun } from './AgentRun'
import type { RunState } from './types'
import { useAgentRun } from './useAgentRun'

/** "Verify this clinic by SMS": the verifier asks the officer in charge, and the interval narrows. Sandbox only. */
export function VerifyPanel({ id, name }: { id: string; name: string }) {
  const run = useAgentRun('verifier')
  const recs = useAsync(() => api.recordings(), [])
  const rec = recs.data?.recordings.find((r) => r.agent === 'verifier' && r.facility_id)
  const [fridge, setFridge] = useState('3')
  const [hours, setHours] = useState('')
  const s = run.state
  const isRecorded = MODE === 'fixture' ? id === 'WL-0001' : rec?.facility_id === id
  const busy = s.status === 'running'

  if (MODE === 'fixture' && !isRecorded) {
    return (
      <div className="card">
        <h2 style={{ fontSize: '1.2rem' }}>Verify this clinic by SMS</h2>
        <p className="muted" style={{ margin: 0 }}>A recorded sample exists for <Link to="/facility/WL-0001">WL-0001</Link>; live runs start when the API is connected.</p>
      </div>
    )
  }
  const controls = (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>
        The verifier asks the officer in charge which fridge holds the vaccines and how many grid hours they had, then re-runs the night. Sandbox, simulated replies: no clinic is contacted and no SMS is sent.
        {MODE === 'live' && rec && !isRecorded && <> A recorded session exists for <Link to={`/facility/${rec.facility_id}`}>another facility</Link>.</>}
      </p>
      {isRecorded ? (
        <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => run.start(MODE === 'fixture' ? { path: '' } : { path: `/agent/verify/${encodeURIComponent(id)}`, body: { recorded: true, recording: rec!.name } })}>
            <Icon name="play" /> {busy ? 'Running…' : 'Replay the recorded session'}
          </button>
          {s.status !== 'idle' && !busy && <button className="btn" onClick={run.reset}>Clear</button>}
        </div>
      ) : (
        <form className="grid2" style={{ alignItems: 'end' }} onSubmit={(e) => { e.preventDefault(); run.start({ path: `/agent/verify/${encodeURIComponent(id)}`, body: { replies: [fridge, hours].filter(Boolean) } }) }}>
          <label className="field small">Typed reply 1: which fridge?
            <select value={fridge} onChange={(e) => setFridge(e.target.value)}><option value="1">1 ice-lined</option><option value="2">2 solar</option><option value="3">3 household</option><option value="4">4 none</option></select>
          </label>
          <label className="field small">Typed reply 2: grid hours yesterday
            <input type="text" inputMode="numeric" value={hours} onChange={(e) => setHours(e.target.value.replace(/[^\d]/g, '').slice(0, 2))} placeholder="0 to 24" />
          </label>
          <div className="row"><button className="btn primary" type="submit" disabled={busy}><Icon name="play" /> {busy ? 'Running…' : 'Run with these replies'}</button>{s.status !== 'idle' && !busy && <button className="btn" type="button" onClick={run.reset}>Clear</button>}</div>
        </form>
      )}
    </div>
  )
  return (
    <AgentRun run={run} title="Verify this clinic by SMS" question={isRecorded && rec?.question ? rec.question : `Verify ${name} by SMS`} badge={`${isRecorded ? 'Recorded session · ' : ''}sandbox, simulated replies`} controls={controls}>
      {(st) => <Conversation s={st} />}
    </AgentRun>
  )
}

function Conversation({ s }: { s: RunState }) {
  const bubbles: { dir: 'out' | 'in'; text: string; key: string }[] = []
  const stages: { label: string; lo: number; hi: number; p: number | null }[] = []
  for (const t of s.tools) {
    const out = t.args.message ?? t.args.text
    if ((t.name === 'ask_clinic' || t.name === 'sms.send') && out) bubbles.push({ dir: 'out', text: String(out), key: `${t.id}o` })
    const reply = t.result?.reply ?? t.result?.data?.sms_reply
    if (reply) bubbles.push({ dir: 'in', text: reply, key: `${t.id}i` })
    const iv = t.result?.interval ?? t.result?.data?.interval
    if (iv) {
      const p = 'point' in iv ? iv.point ?? null : (iv as { p?: number | null }).p ?? null
      stages.push({ label: (t.result?.interval?.scenario ?? t.result?.data?.stage ?? t.name) as string, lo: iv.lo, hi: iv.hi, p })
    }
  }
  if (!bubbles.length && !stages.length) return null
  const cur = stages[stages.length - 1]
  return (
    <div className="grid2" style={{ gap: 14 }}>
      <div className="chat" aria-label="SMS conversation (sandbox, simulated replies)">
        {bubbles.map((b) => <div key={b.key} className={`bubble ${b.dir}`}>{b.text}</div>)}
      </div>
      {cur && (
        <div className="stack">
          <strong className="small">Days at 2 to 8 °C: the interval after each reply</strong>
          <div className="narrow" role="img" aria-label={`${cur.label}: ${pct(cur.lo)} to ${pct(cur.hi)}`}>
            <div className="span" style={{ left: `${cur.lo * 100}%`, width: `${Math.max(1, (cur.hi - cur.lo) * 100)}%` }} />
            {cur.p !== null && <div className="pt" style={{ left: `${cur.p * 100}%` }} />}
          </div>
          <ol className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {stages.map((st, i) => <li key={i} className={i === stages.length - 1 ? '' : 'muted'}><span className="mono">{pct(st.lo)} to {pct(st.hi)}</span> ({st.label})</li>)}
          </ol>
        </div>
      )}
    </div>
  )
}
