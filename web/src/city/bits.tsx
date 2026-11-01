import type { ReactNode } from 'react'
import type { DataSource, EvidenceLabel, Range } from '../api/brief13'
import { span } from './format'

const LABEL_TEXT: Record<EvidenceLabel, { cls: string; title: string; glyph: ReactNode }> = {
  VERIFIED: { cls: 'lc-ok', title: 'Verified: taken from a quoted source', glyph: <path d="M4 10.5l3.5 3.5L16 5.5" /> },
  ASSUMPTION: { cls: 'lc-as', title: 'Assumption: a stated design value or range, unmeasured', glyph: <path d="M4 11c2-3 4-3 6 0s4 3 6 0" /> },
  UNVERIFIED: { cls: 'lc-un', title: 'Unverified: a placeholder until a source is found', glyph: <><path d="M7.5 7.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.5v.7" /><circle cx="10" cy="15" r=".6" fill="currentColor" /></> },
}

export function LabelChip({ label, note }: { label: EvidenceLabel | null; note?: string | null }) {
  if (!label) return null
  const t = LABEL_TEXT[label]
  return (
    <span className={`lchip ${t.cls}`} title={note ? `${t.title}. ${note}` : t.title}>
      <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{t.glyph}</svg>
      {label}
    </span>
  )
}

export function SourceBadge({ src }: { src?: DataSource }) {
  if (src === 'mock') return <span className="mockb" title="Placeholder numbers from the web app's own mock, shown until the engine serves this view">Mock data</span>
  if (src === 'fixture') return <span className="fxb" title="Recorded engine output, served from a file because the live API did not answer">Recorded engine output</span>
  return null
}

export function Segmented<T extends string | number>({ label, value, options, onChange, id }: {
  label: string; value: T; options: { value: T; label: ReactNode; hint?: string }[]; onChange: (v: T) => void; id: string
}) {
  return (
    <div className="seg-wrap">
      <span className="seg-label" id={`${id}-l`}>{label}</span>
      <div className="seg" role="radiogroup" aria-labelledby={`${id}-l`}>
        {options.map((o) => (
          <button key={String(o.value)} type="button" role="radio" aria-checked={o.value === value} className={o.value === value ? 'on' : ''}
            onClick={() => onChange(o.value)} title={o.hint}
            onKeyDown={(e) => {
              const i = options.findIndex((x) => x.value === value)
              if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); onChange(options[(i + 1) % options.length].value) }
              if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); onChange(options[(i - 1 + options.length) % options.length].value) }
            }}
            tabIndex={o.value === value ? 0 : -1}>
            <span>{o.label}</span>{o.hint && <small>{o.hint}</small>}
          </button>
        ))}
      </div>
    </div>
  )
}

/** The interval under a headline, or nothing when the API sent none. */
export function RangeLine({ r, f, prefix = 'range' }: { r: Range; f: (n: number) => string; prefix?: string }) {
  const s = span(r, f)
  return s ? <span className="rangeline">{prefix} {s}</span> : null
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty" role="status">{children}</div>
}
