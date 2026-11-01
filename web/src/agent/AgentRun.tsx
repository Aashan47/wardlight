import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { Icon } from '../components/ui'
import { useReducedMotion } from '../hooks'
import { Link } from '../router'
import type { AgentRunHandle } from './useAgentRun'
import type { Check, CheckedNumber, Citation, RunState } from './types'
import { share } from '../city/format'

const isFacilityId = (s: string) => /^(WL-\d+|SN_[0-9A-F]+|v[23]_[0-9a-f-]{20,})$/.test(s)
/** brief 13 site ids: H-<GRID3 id>, W-BH-<n>, W-WORKS-<n>, C-<OSM id> */
const isSiteId = (s: string) => /^(H-SN_[0-9A-F]+|W-[A-Z]+-\d+|C-\d+)$/.test(s)
const idLink = (s: string) => (isSiteId(s) ? `/site/${encodeURIComponent(s)}` : `/facility/${encodeURIComponent(s)}`)

/** Small markdown: # headings, **bold**, *italic*, "- " and "1. " lists, | tables |, paragraphs, [S7] source chips and
 *  [[id]] facility chips. */
export function Markdown({ text, cites = [] }: { text: string; cites?: Citation[] }) {
  const clean = text.replace(/\[\[?[^\]]*$/, '')
  const inline = (s: string, k: string) => s.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[\[[^\]]+\]\]|\[S\d+\])/g).map((part, i) => {
    const key = `${k}${i}`
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={key}>{part.slice(2, -2)}</strong>
    if (part.length > 2 && part.startsWith('*') && part.endsWith('*')) return <em key={key}>{inline(part.slice(1, -1), `${key}e`)}</em>
    if (part.startsWith('[[') && part.endsWith(']]')) { const id = part.slice(2, -2); return <Link key={key} className="cite" to={`/facility/${id}`}><Icon name="doc" size={11} />{id}</Link> }
    if (/^\[S\d+\]$/.test(part)) {
      const id = part.slice(1, -1); const c = cites.find((x) => x.cite === id)
      const title = c ? (c.file ? `${c.file}, page ${c.page}, row ${c.sn}` : c.source_type ?? id) : id
      return c?.facility_id ? <Link key={key} className="cite" to={`/facility/${c.facility_id}`} title={title}>{id}</Link> : <a key={key} className="cite" href={`#cite-${id}`} title={title}>{id}</a>
    }
    return <Fragment key={key}>{part.replace(/\*\*/g, '')}</Fragment>
  })
  const lines = clean.split('\n')
  const out: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => { if (list) { const L = list.ordered ? 'ol' : 'ul'; out.push(<L key={`l${out.length}`}>{list.items.map((it, j) => <li key={j}>{inline(it, `l${out.length}-${j}-`)}</li>)}</L>); list = null } }
  let para: string[] = []
  const flushP = () => { if (para.length) { out.push(<p key={`p${out.length}`}>{inline(para.join(' '), `p${out.length}-`)}</p>); para = [] } }
  // live models answer in tables: header row, |---| rule, body rows
  let table: string[][] | null = null
  const cells = (l: string) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
  const flushT = () => {
    if (!table) return
    const [head, ...body] = table, k = `t${out.length}`
    out.push(<div key={k} className="md-table"><table>
      <thead><tr>{head.map((c, j) => <th key={j} scope="col">{inline(c, `${k}h${j}-`)}</th>)}</tr></thead>
      <tbody>{body.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{inline(c, `${k}r${i}c${j}-`)}</td>)}</tr>)}</tbody>
    </table></div>)
    table = null
  }
  for (const l of lines) {
    if (/^\s*\|\s*$/.test(l)) continue  // a stray pipe left after a table
    if (/^\s*\|.*\|\s*$/.test(l)) {
      flushP(); flush()
      if (/^\s*\|?[\s:|-]+\|?\s*$/.test(l) && l.includes('-')) continue
      ;(table ??= []).push(cells(l)); continue
    }
    flushT()
    const ul = /^\s*- (.*)$/.exec(l), ol = /^\s*\d+\. (.*)$/.exec(l), h = /^(#{1,3}) (.*)$/.exec(l)
    if (ul || ol) { flushP(); const ordered = !!ol; if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] } } list.items.push((ul ?? ol)![1]); continue }
    flush()
    if (h) { flushP(); out.push(<p key={`h${out.length}`} className="md-h"><strong>{inline(h[2], `h${out.length}-`)}</strong></p>); continue }
    if (!l.trim()) { flushP(); continue }
    para.push(l)
  }
  flush(); flushP(); flushT()
  return <>{out}</>
}

export function CountUp({ value, format = (n) => n.toLocaleString('en-US') }: { value: number; format?: (n: number) => string }) {
  const reduced = useReducedMotion()
  const [v, setV] = useState(reduced ? value : 0)
  useEffect(() => {
    if (reduced) { setV(value); return }
    let raf = 0; const t0 = performance.now(), dur = 500
    const tick = (now: number) => { const k = Math.min(1, (now - t0) / dur); setV(value * (1 - (1 - k) ** 3)); if (k < 1) raf = requestAnimationFrame(tick) }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, reduced])
  return <span className="mono">{format(Math.round(v))}</span>
}

function StreamedAnswer({ text, cites }: { text: string; cites: Citation[] }) {
  const reduced = useReducedMotion()
  const [n, setN] = useState(reduced ? text.length : 0)
  useEffect(() => {
    if (reduced) { setN(text.length); return }
    let raf = 0; const t0 = performance.now(), dur = Math.min(2200, text.length * 4)
    const tick = (now: number) => { const k = Math.min(1, (now - t0) / dur); setN(Math.round(text.length * k)); if (k < 1) raf = requestAnimationFrame(tick) }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [text, reduced])
  return <div className="answer-text"><Markdown text={text.slice(0, n)} cites={cites} />{n < text.length && <span className="caret" aria-hidden="true" />}</div>
}

function Args({ args }: { args: Record<string, unknown> }) {
  return (
    <code className="args">
      {Object.entries(args).map(([k, v], i) => {
        const val = Array.isArray(v) ? v : [v]
        return (
          <span key={k}>{i > 0 && ', '}{k}: {val.map((x, j) => {
            const s = typeof x === 'object' && x !== null ? JSON.stringify(x) : String(x)
            return <Fragment key={j}>{j > 0 && ', '}{isFacilityId(s) || isSiteId(s) ? <Link to={idLink(s)}>{s}</Link> : typeof x === 'string' ? `"${s}"` : s}</Fragment>
          })}</span>
        )
      })}
    </code>
  )
}

function Grounding({ check, n }: { check: Check; n: number }) {
  const reduced = useReducedMotion()
  // matches lists every number checked, the unmatched ones with matched: null; those show once, as the red chips
  const unmatched = new Set(check.unmatched)
  const nums: CheckedNumber[] = (check.matches ?? (Array.isArray(check.numbers_checked) ? check.numbers_checked : []))
    .filter((x) => !(x.matched == null && !x.tool && unmatched.has(x.text)))
  const total = Array.isArray(check.numbers_checked) ? check.numbers_checked.length : check.numbers_checked
  const [shown, setShown] = useState(reduced ? nums.length : 0)
  useEffect(() => {
    if (reduced) { setShown(nums.length); return }
    if (shown >= nums.length) return
    const h = setTimeout(() => setShown((x) => x + 1), nums.length > 20 ? 45 : 110)
    return () => clearTimeout(h)
  }, [shown, nums.length, reduced])
  const ok = check.unmatched.length === 0
  return (
    <div className={`ground ${ok ? '' : 'bad'}`}>
      <div className="row between"><strong className="small">Grounding check{n > 0 ? ` (attempt ${n + 1})` : ''}</strong>
        <span className={`tag ${ok ? 's-cell' : 's-risk'}`}><Icon name={ok ? 'check' : 'x'} size={13} />{ok ? `${total} numbers traced to tool results` : `${check.unmatched.length} unmatched: answer blocked`}</span></div>
      <div className="chips" style={{ marginTop: 8 }}>
        {check.unmatched.map((u) => <span key={`u${u}`} className="chip num bad on"><Icon name="x" size={11} />{u}<span className="muted"> no tool result</span></span>)}
        {nums.map((x, i) => (
          <span key={i} className={`chip num ${i < shown ? 'on' : ''}`} title={x.tool ? `From tool call ${x.tool}` : x.matched != null ? `Matched ${x.matched}` : ''}>
            {i < shown ? <Icon name="check" size={11} /> : <span className="dot" />}{x.text}{x.tool && <span className="muted"> ← {x.tool}</span>}
          </span>
        ))}
      </div>
    </div>
  )
}

const TOTALS: [string, string, 'ngn' | 'n' | 'share'][] = [
  ['funded_count', 'Sites funded', 'n'], ['spent_ngn', 'Spent', 'ngn'], ['share_with_funded', 'Critical service-hours kept', 'share'], ['diesel_l_avoided', 'Diesel avoided, litres', 'n'],
  ['own_solar', 'Sites on their own solar', 'n'], ['dark', 'Sites dark unless fuelled', 'n'], ['window_days', 'Outage, days', 'n'],
  ['benefit_total', 'Benefit', 'n'], ['remaining_ngn', 'Left over', 'ngn'],
  ['changed', 'Feeders changed', 'n'], ['facilities_affected', 'Facilities affected', 'n'], ['fix_changed', 'Fix changed', 'n'],
]
const ngnFmt = (n: number) => (n >= 1e9 ? `N${(n / 1e9).toFixed(2)}bn` : `N${(n / 1e6).toFixed(1)}m`)

export function AgentRun({ run, title, question, badge, children, controls, startLabel, askLabel }: {
  run: AgentRunHandle; title: string; question: string; badge?: string; children?: (s: RunState) => ReactNode
  controls?: ReactNode; startLabel?: string; askLabel?: string
}) {
  const s = run.state
  const running = s.status === 'running'
  const lastTool = s.tools[s.tools.length - 1]
  const thinking = running && !s.answer && (!lastTool || !!lastTool.result)
  const recorded = s.done?.recorded ?? s.info?.recorded
  const unit = typeof s.answer?.totals?.benefit_unit === 'string' ? s.answer.totals.benefit_unit : ''
  const cites = s.citations
  const evidence = cites.filter((c) => c.row_text)
  return (
    <section className="agent card" aria-label={title}>
      <div className="row between">
        <h2 style={{ margin: 0, fontSize: '1.2rem' }}><span className="agent-mark" aria-hidden="true" />{title}</h2>
        {(badge || recorded !== undefined) && <span className="tag s-sun">{badge ?? (recorded ? 'Recorded session' : 'Live')}</span>}
      </div>
      <div className="ask">
        <span className="kicker" style={{ margin: 0 }}>{askLabel ?? (recorded ? 'Recorded question' : 'Question')}</span>
        <p style={{ margin: '2px 0 0' }}>{askLabel ? s.info?.recorded_question ?? question : <>“{s.info?.recorded_question ?? question}”</>}</p>
      </div>
      {controls}
      {startLabel && (
        <div className="row"><span className="small muted">{running ? 'Running…' : startLabel}</span>{s.status !== 'idle' && !running && <button className="btn small" onClick={run.reset}>Clear</button>}</div>
      )}
      {s.info?.recording_label && <p className="small muted" style={{ margin: 0 }}>{s.info.recording_label}</p>}

      {s.steps.length > 0 && (
        <ol className="steps" aria-label="Agent plan">
          {s.steps.map((st, i) => (
            <li key={st.id} className={`step ${st.state}`} style={{ animationDelay: `${i * 60}ms` }}>
              <span className="tick" aria-hidden="true">{st.state === 'done' ? <Icon name="check" size={12} /> : st.state === 'active' ? <span className="spin" /> : null}</span>
              {st.title}<span className="sr-only"> ({st.state})</span>
            </li>
          ))}
        </ol>
      )}

      {thinking && <div className="thinking" role="status"><span className="shimmer">Thinking</span></div>}

      {s.reasoning.length > 0 && (
        <details className="reasoning" open={s.reasoning.some((r) => r.source === 'model')}>
          <summary>The model's stated reasoning ({s.reasoning.length})</summary>
          {s.reasoning.map((r, i) => <p key={i}>{r.text}</p>)}
        </details>
      )}

      {s.tools.length > 0 && (
        <div className="tools">
          {s.tools.map((t) => (
            <div key={t.id} className={`tool ${t.result ? 'has-result' : 'pending'}`}>
              <div className="row between" style={{ gap: 6 }}><span className="mono tool-name">{t.name}</span><span className="small muted mono">{t.result ? `${t.result.rows.toLocaleString('en-US')} rows${t.result.ms != null ? ` · ${t.result.ms.toLocaleString('en-US')} ms` : ''}` : 'running'}</span></div>
              <Args args={t.args} />
              {t.result ? <p className="result">{t.result.summary}</p> : <div className="bar-shimmer" aria-hidden="true" />}
            </div>
          ))}
        </div>
      )}

      {children?.(s)}

      {evidence.length > 0 && (
        <div className="cited">
          <strong className="small">Evidence cited</strong>
          {evidence.slice(0, 4).map((c, i) => {
            const [a, b, loc, hrs] = (c.row_text ?? '').split(' | ')
            return (
              <div key={`${c.cite}${i}`} id={c.cite ? `cite-${c.cite}` : undefined} className="nerc flash" style={{ marginTop: 6, animationDelay: `${i * 120}ms` }}>
                <dl>
                  <dt>Feeder</dt><dd>{a}</dd>{b && <><dt>Station</dt><dd>{b}</dd></>}{loc && <><dt>Serving</dt><dd>{loc}</dd></>}{hrs && <><dt>Min. supply</dt><dd>{hrs} hours</dd></>}
                </dl>
                <p className="small muted" style={{ margin: 0, padding: '6px 12px' }}>{c.cite && <span className="cite" style={{ marginRight: 6 }}>{c.cite}</span>}{c.file}, page {c.page}, row {c.sn}{c.facility_id && <> · <Link to={`/facility/${c.facility_id}`}>facility</Link></>}</p>
              </div>
            )
          })}
          {evidence.length > 4 && <p className="small muted" style={{ margin: '6px 0 0' }}>and {evidence.length - 4} more NERC rows cited</p>}
        </div>
      )}

      {s.checks.map((c, i) => <Grounding key={i} check={c} n={s.checks.length > 1 ? i : 0} />)}

      {s.answer && (
        <div className="answer">
          <StreamedAnswer text={s.answer.markdown} cites={cites} />
          {(() => {
            const t = s.answer!.totals ?? {}
            const shown = TOTALS.filter(([k]) => typeof t[k] === 'number').slice(0, 4)
            return shown.length > 0 && (
              <div className="metrics" style={{ marginTop: 10 }}>
                {shown.map(([k, label, f]) => (
                  <div key={k}><div className="kicker">{k === 'benefit_total' && unit ? unit : label}</div><div className="counter">{f === 'share' ? <span className="mono">{share(t[k] as number)}</span> : <CountUp value={t[k] as number} format={f === 'ngn' ? ngnFmt : undefined} />}</div></div>
                ))}
              </div>
            )
          })()}
          {s.answer.not_reached.length > 0 && (
            <div style={{ marginTop: 10 }}><strong className="small">What the money does not reach</strong>
              <ul className="small">
                {s.answer.not_reached.slice(0, 5).map((n, i) => typeof n === 'string' ? <li key={i}><Markdown text={n} /></li>
                  : n.text ? <li key={i}><Markdown text={n.text} /></li>
                  : <li key={i}>{n.rank ? <span className="mono">#{n.rank} </span> : null}{n.unique_id ? <Link to={idLink(n.unique_id)}>{n.name ?? n.unique_id}</Link> : n.name}{n.why_not_funded ? `: ${n.why_not_funded}` : ''}</li>)}
              </ul>
              {s.answer.not_reached.length > 5 && <p className="small muted" style={{ margin: 0 }}>and {s.answer.not_reached.length - 5} more listed by the agent</p>}
            </div>
          )}
        </div>
      )}

      {s.error && <div className="banner" role="alert">{s.error}</div>}

      {s.done && (
        <footer className="agent-foot mono small">
          <span>model: {s.done.model}</span><span>tokens: {s.done.tokens.toLocaleString('en-US')}</span><span>cost: US${s.done.cost_usd.toFixed(4)}</span>
          <span>run time {(s.done.duration_ms / 1000).toFixed(1)} s{s.info?.speed && s.info.speed !== 1 ? `, replayed at ${s.info.speed}x` : ''}</span>
          <span>{s.done.recorded ? (s.done.sample ? 'recorded sample' : 'recorded session') : 'live'}</span>
          {s.done.status && <span>status: {s.done.status}</span>}
        </footer>
      )}
      <ol className="sr-only" aria-live="polite" aria-label="Agent event log">{s.log.slice(-1).map((l, i) => <li key={i}>{l}</li>)}</ol>
    </section>
  )
}
