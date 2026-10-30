import { useCallback, useEffect, useReducer, useRef } from 'react'
import { apiUrl, BASE, MODE } from '../api/client'
import { useReducedMotion } from '../hooks'
import type { AgentEvent, AgentKind, RunInfo, RunState } from './types'

const INIT: RunState = { status: 'idle', steps: [], reasoning: [], tools: [], citations: [], checks: [], log: [] }

function summary(e: AgentEvent): string {
  switch (e.type) {
    case 'plan': return `Plan: ${e.data.steps.map((s) => s.title).join('; ')}`
    case 'step_start': return `Step: ${e.data.id}`
    case 'reasoning': return 'The model stated its reasoning'
    case 'tool_call': return `Calling ${e.data.name}`
    case 'tool_result': return `Result: ${e.data.summary}`
    case 'check': { const n = Array.isArray(e.data.numbers_checked) ? e.data.numbers_checked.length : e.data.numbers_checked; return `Grounding check: ${n} numbers, ${e.data.unmatched.length} unmatched` }
    case 'citation': return `Cited ${e.data.cite ?? ''} ${e.data.file ?? e.data.source_type ?? ''}`
    case 'answer': return 'Answer ready'
    case 'error': return `Error: ${e.data.message}`
    case 'done': return 'Run finished'
  }
}

type Action = AgentEvent | { type: 'reset' } | { type: 'start'; info?: RunInfo } | { type: 'info'; info: RunInfo }
function reduce(s: RunState, e: Action): RunState {
  if (e.type === 'reset') return INIT
  if (e.type === 'start') return { ...INIT, status: 'running', info: e.info, log: ['Run started'] }
  if (e.type === 'info') return { ...s, info: { ...s.info, ...e.info } }
  const log = [...s.log, summary(e)]
  switch (e.type) {
    case 'plan': return { ...s, log, steps: e.data.steps.map((st) => ({ ...st, state: 'pending' })) }
    case 'step_start': {
      const at = s.steps.findIndex((st) => st.id === e.data.id)
      if (at < 0) return { ...s, log }
      // a step may start again (draft and check on a retry): later steps go back to pending
      return { ...s, log, steps: s.steps.map((st, i) => ({ ...st, state: i < at ? 'done' : i === at ? 'active' : 'pending' })) }
    }
    case 'reasoning': return { ...s, log, reasoning: [...s.reasoning, { text: e.data.text, source: e.data.source }] }
    case 'tool_call': return { ...s, log, tools: [...s.tools, { id: e.data.id, name: e.data.name, args: e.data.args ?? {} }] }
    case 'tool_result': return { ...s, log, tools: s.tools.map((t) => (t.id === e.data.id ? { ...t, result: e.data } : t)) }
    case 'check': return { ...s, log, checks: [...s.checks, e.data] }
    case 'citation': return { ...s, log, citations: [...s.citations, e.data] }
    case 'answer': return { ...s, log, answer: e.data }
    case 'error': return { ...s, log, status: 'error', error: e.data.message }
    case 'done': return { ...s, log, status: s.status === 'error' ? 'error' : 'done', done: e.data, steps: s.steps.map((st) => ({ ...st, state: 'done' })) }
  }
}

/** Accepts agent F's flat events ({type, seq, t_ms, ...payload}) and the sample replays ({t, type, data}). */
function normalize(raw: Record<string, unknown>): AgentEvent | null {
  const type = raw.type as AgentEvent['type'] | undefined
  if (!type) return null
  const data = (raw.data && typeof raw.data === 'object' && type !== 'tool_result' ? raw.data : raw) as never
  if (type === 'tool_result' && raw.data && !('summary' in raw)) return { type, data: raw.data as never }
  return { type, data } as AgentEvent
}

export interface StartOptions { body?: Record<string, unknown>; path: string; method?: 'POST' | 'GET'; speed?: number }

/**
 * Runs an agent. Live: POST starts the run (202 with run_id and events_url), then GET streams the events as SSE.
 * Fixture mode: replays /fixtures/agent-<kind>.json. Events are shown at least ~260 ms apart so each step can be
 * seen (instant with reduced motion); the cards still show each tool's real milliseconds.
 */
export function useAgentRun(kind: AgentKind) {
  const reduced = useReducedMotion()
  const [state, dispatch] = useReducer(reduce, INIT)
  const timers = useRef<number[]>([])
  const abort = useRef<AbortController | null>(null)
  const queue = useRef<AgentEvent[]>([])
  const pump = useRef<number | null>(null)
  const gap = reduced ? 0 : 260

  const stop = useCallback(() => {
    timers.current.forEach(clearTimeout); timers.current = []
    if (pump.current) clearTimeout(pump.current); pump.current = null
    queue.current = []
    abort.current?.abort(); abort.current = null
  }, [])
  useEffect(() => stop, [stop])

  const enqueue = useCallback((ev: AgentEvent) => {
    queue.current.push(ev)
    const drain = () => {
      const next = queue.current.shift()
      if (!next) { pump.current = null; return }
      dispatch(next)
      pump.current = window.setTimeout(drain, queue.current.length > 40 ? 30 : gap)
    }
    if (pump.current === null) drain()
  }, [gap])

  const start = useCallback(async (opts: StartOptions) => {
    stop()
    dispatch({ type: 'start' })
    if (MODE === 'fixture') {
      try {
        const r = await (await fetch(`/fixtures/agent-${kind}.json`)).json() as { label: string; question: string; events: (Record<string, unknown> & { t: number })[] }
        dispatch({ type: 'info', info: { recorded: true, label: r.label, recorded_question: r.question } })
        r.events.forEach((ev) => { timers.current.push(window.setTimeout(() => { const n = normalize(ev); if (n) enqueue(n) }, ev.t)) })
      } catch (err) { dispatch({ type: 'error', data: { message: `Could not load the recorded session (${String(err)})` } }) }
      return
    }
    const ac = new AbortController(); abort.current = ac
    try {
      const startRes = await fetch(`${BASE}${opts.path}`, {
        method: opts.method ?? 'POST', signal: ac.signal,
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: (opts.method ?? 'POST') === 'POST' ? JSON.stringify(opts.body ?? {}) : undefined,
      })
      const info = await startRes.json().catch(() => ({})) as RunInfo & { events_url?: string; error?: string; detail?: string }
      if (!startRes.ok || !info.events_url) throw new Error(info.detail ?? info.error ?? `${startRes.status} ${startRes.statusText}`)
      dispatch({ type: 'info', info: { ...info, speed: opts.speed } })
      const res = await fetch(apiUrl(info.events_url), { headers: { Accept: 'text/event-stream' }, signal: ac.signal })
      if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`)
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = ''
      for (;;) {
        const { value, done } = await reader.read(); if (done) break
        buf += dec.decode(value, { stream: true })
        let cut
        while ((cut = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, cut); buf = buf.slice(cut + 2)
          const data = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.replace(/^data: ?/, '')).join('\n')
          if (!data) continue // comment keep-alive
          const parsed = JSON.parse(data) as Record<string, unknown>
          const type = /^event: ?(.*)$/m.exec(block)?.[1]?.trim()
          const n = normalize({ type, ...parsed })
          if (n) enqueue(n)
        }
      }
    } catch (err) {
      if (!ac.signal.aborted) enqueue({ type: 'error', data: { message: String(err instanceof Error ? err.message : err) } })
    }
  }, [kind, stop, enqueue])

  const reset = useCallback(() => { stop(); dispatch({ type: 'reset' }) }, [stop])
  return { state, start, reset, mode: MODE }
}
export type AgentRunHandle = ReturnType<typeof useAgentRun>
