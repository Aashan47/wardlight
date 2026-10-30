// Agent event stream (11-AGENTS-DESIGN.md; agents/events.py). Every event is {type, seq, t_ms, ...payload};
// the UI keeps the payload as `data`. Extra keys are allowed and read when present.
export type AgentKind = 'planner' | 'verifier' | 'watcher'

export interface Step { id: string; title: string }
export interface Interval { p: number | null; lo: number; hi: number }
export interface BandChange { feeder_id: string; name: string; from: string; to: string; from_hours: number; to_hours: number; facilities: string[] | number; disco?: string; state?: string; linked?: boolean }
export interface CheckedNumber { text: string; tool?: string; value?: number; matched?: number | null }

export interface ToolResult {
  id: string; summary: string; rows: number; ms: number | null; ok?: boolean
  // verifier extras (agents/events.py), and the sample replays' `data`
  reply?: string; parsed?: unknown; interval?: { point?: number | null; p?: number | null; lo: number; hi: number; scenario?: string }
  data?: { considering?: string[]; funded?: string[]; budget_ngn?: number; interval?: Interval; stage?: string; sms_reply?: string; changes?: BandChange[] }
}
export interface Check { kind: 'grounding'; numbers_checked: CheckedNumber[] | number; unmatched: string[]; matches?: CheckedNumber[]; ok?: boolean }
export interface Citation { facility_id: string | null; file: string | null; page: number | null; sn: number | string | null; row_text: string | null; cite?: string; source_type?: string }
export interface FundedItem { unique_id: string; name?: string; rank?: number; cost_ngn?: number }
export interface NotReached { text?: string; unique_id?: string; name?: string; why_not_funded?: string; rank?: number }
export interface Answer {
  markdown: string; funded: (string | FundedItem)[]; not_reached: (string | NotReached)[]; totals: Record<string, number | string | null>
  status?: string; changes?: RawChange[]
}
export interface RawChange { feeder_id: string; feeder_name: string; disco: string; state: string; band_old: string; band_new: string; linked: boolean; facilities_matched: number }
export interface Done { model: string; tokens: number; cost_usd: number; recorded: boolean; sample?: boolean; duration_ms: number; label?: string; status?: string }

export type AgentEvent =
  | { type: 'plan'; data: { steps: Step[] } }
  | { type: 'step_start'; data: { id: string } }
  | { type: 'reasoning'; data: { text: string; source: 'model' | 'sample' } }
  | { type: 'tool_call'; data: { id: string; name: string; args: Record<string, unknown> } }
  | { type: 'tool_result'; data: ToolResult }
  | { type: 'check'; data: Check }
  | { type: 'citation'; data: Citation }
  | { type: 'answer'; data: Answer }
  | { type: 'error'; data: { message: string } }
  | { type: 'done'; data: Done }

export interface ToolCard { id: string; name: string; args: Record<string, unknown>; result?: ToolResult }
export interface RunInfo { run_id?: string; recorded?: boolean; label?: string; recording_label?: string; recorded_question?: string; mode?: string; speed?: number }
export interface RunState {
  status: 'idle' | 'running' | 'done' | 'error'
  info?: RunInfo
  steps: (Step & { state: 'pending' | 'active' | 'done' })[]
  reasoning: { text: string; source: string }[]
  tools: ToolCard[]
  citations: Citation[]
  checks: Check[]
  answer?: Answer
  error?: string
  done?: Done
  log: string[]
}
