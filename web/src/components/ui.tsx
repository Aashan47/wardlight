import type { ReactNode } from 'react'
import type { CapFields, FixCategory, Interval, ScenarioFields, Tier } from '../api/types'
import { num } from '../format'
import { pct } from '../format'

type IconName = 'check' | 'x' | 'q' | 'grid' | 'sun' | 'battery' | 'pin' | 'doc' | 'print' | 'download' | 'phone' | 'moon' | 'light' | 'play' | 'pause' | 'search' | 'offline'
const P: Record<IconName, ReactNode> = {
  check: <path d="M4 10.5l3.5 3.5L16 5.5" />,
  x: <path d="M5 5l10 10M15 5L5 15" />,
  q: <><path d="M7.5 7.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.5v.7" /><circle cx="10" cy="15" r=".6" fill="currentColor" /></>,
  grid: <path d="M11 2L5 11h5l-1 7 6-9h-5l1-7z" />,
  sun: <><circle cx="10" cy="10" r="3.5" /><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4" /></>,
  battery: <><rect x="3" y="6" width="12" height="8" rx="1.5" /><path d="M17 9v2" /></>,
  pin: <><path d="M10 18s5-5.2 5-9a5 5 0 0 0-10 0c0 3.8 5 9 5 9z" /><circle cx="10" cy="9" r="1.8" /></>,
  doc: <><path d="M5 2.5h6l4 4v11H5z" /><path d="M11 2.5v4h4M7.5 11h5M7.5 14h5" /></>,
  print: <><path d="M6 7V3h8v4M6 14H4V8h12v6h-2" /><rect x="6" y="12" width="8" height="5" /></>,
  download: <path d="M10 3v10M6 9l4 4 4-4M4 16h12" />,
  phone: <><rect x="6" y="2.5" width="8" height="15" rx="1.5" /><path d="M9 15h2" /></>,
  moon: <path d="M15.5 12.5A6 6 0 0 1 7.5 4.5a6 6 0 1 0 8 8z" />,
  light: <><circle cx="10" cy="10" r="3.2" /><path d="M10 2.5v1.8M10 15.7v1.8M2.5 10h1.8M15.7 10h1.8" /></>,
  play: <path d="M6 4l10 6-10 6z" fill="currentColor" />,
  pause: <path d="M6 4h3v12H6zM11 4h3v12h-3z" fill="currentColor" />,
  search: <><circle cx="9" cy="9" r="5" /><path d="M13 13l4 4" /></>,
  offline: <><path d="M3 8.5a10 10 0 0 1 14 0M5.5 11a6.5 6.5 0 0 1 9 0M8 13.5a3 3 0 0 1 4 0" /><circle cx="10" cy="16" r=".8" fill="currentColor" /></>,
}
export function Icon({ name, size = 16, label }: { name: IconName; size?: number; label?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden={label ? undefined : true} role={label ? 'img' : undefined} aria-label={label}>
      {P[name]}
    </svg>
  )
}

export function SampleBadge({ children = 'Sample data' }: { children?: ReactNode }) {
  return <span className="sample" title="Synthetic numbers from the fixture generator, shown until the engine lands">{children}</span>
}

export const TIER: Record<Tier, { label: string; cls: string; icon: IconName; long: string }> = {
  a_named: { label: 'Tier a: named in a feeder row', cls: 's-grid', icon: 'doc', long: 'The facility itself is named in a NERC feeder\'s street list.' },
  b_place: { label: 'Tier b: town or ward named', cls: 's-grid', icon: 'pin', long: 'Its town or ward is named in a feeder row in its state.' },
  c_lga_mixture: { label: 'Tier c: LGA mixture', cls: 's-sun', icon: 'grid', long: 'Only its LGA is matched to feeder rows, so supply is a mixture of the bands of feeders serving that LGA.' },
  c_unit_mixture: { label: 'Tier c: business-unit mixture', cls: 's-sun', icon: 'grid', long: 'Only its DisCo business unit is known, so supply is a mixture of that unit\'s bands.' },
  offgrid: { label: 'Off-grid: modelled with no grid', cls: 's-sun', icon: 'sun', long: 'Far from any predicted grid line, so it is modelled with no grid hours.' },
  d_refused: { label: 'Tier d: refused', cls: 's-unknown', icon: 'q', long: 'No evidence places it on a feeder, so no supply figure is given.' },
}
export function TierTag({ tier }: { tier: Tier }) {
  const t = TIER[tier]
  return <span className={`tag ${t.cls}`}><Icon name={t.icon} size={13} />{t.label}</span>
}

export function Status({ ok, unknown, children }: { ok?: boolean; unknown?: boolean; children?: ReactNode }) {
  if (unknown) return <span className="tag s-unknown"><Icon name="q" size={13} />{children ?? 'Unknown'}</span>
  return ok
    ? <span className="tag s-cell"><Icon name="check" size={13} />{children ?? 'Survives'}</span>
    : <span className="tag s-risk"><Icon name="x" size={13} />{children ?? 'Goes dark'}</span>
}

export function IntervalBar({ v, label }: { v: Interval; label: string }) {
  const color = v.lo >= 0.9 ? 'var(--t-cell)' : v.hi < 0.5 ? 'var(--t-risk)' : 'var(--t-sun)'
  return (
    <div className="ibar" role="img" aria-label={`${label}: ${pct(v.p)}, interval ${pct(v.lo)} to ${pct(v.hi)}`}>
      <div className="span" style={{ left: `${v.lo * 100}%`, width: `${Math.max(1, (v.hi - v.lo) * 100)}%`, background: color }} />
      <div className="pt" style={{ left: `${v.p * 100}%`, background: color }} />
    </div>
  )
}

export function Loading({ what = 'Loading' }: { what?: string }) {
  return <p className="muted mono" role="status">{what}…</p>
}
export function ErrorNote({ error }: { error: Error }) {
  return <div className="banner" role="alert">Could not load this: {error.message}. If you are offline, pages you saved earlier still open.</div>
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="#0E1420" />
      <g fill="none" strokeWidth="6">
        <circle cx="32" cy="32" r="21" stroke="#2a3446" />
        <path d="M32 11a21 21 0 0 1 21 21" stroke="#3D7BD9" />
        <path d="M53 32a21 21 0 0 1-21 21" stroke="#E8A33D" />
      </g>
      <rect x="27" y="24" width="10" height="17" rx="2" fill="#2FA37A" />
      <rect x="29" y="21" width="6" height="3" rx="1" fill="#2FA37A" />
    </svg>
  )
}

/** The 24-hour ring as a section divider. */
export function RingDivider() {
  return (
    <div aria-hidden="true" style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '30px 0 8px' }}>
      <svg width="34" height="34" viewBox="0 0 34 34">
        {Array.from({ length: 24 }, (_, i) => {
          const a0 = (i / 24) * Math.PI * 2 - Math.PI / 2, a1 = ((i + 0.8) / 24) * Math.PI * 2 - Math.PI / 2
          const c = i >= 6 && i < 18 ? 'var(--t-sun)' : i % 3 === 0 ? 'var(--t-grid)' : 'var(--line)'
          return <path key={i} d={`M${17 + 14 * Math.cos(a0)} ${17 + 14 * Math.sin(a0)} A14 14 0 0 1 ${17 + 14 * Math.cos(a1)} ${17 + 14 * Math.sin(a1)}`} stroke={c} strokeWidth="4" fill="none" />
        })}
      </svg>
      <div style={{ flex: 1, height: 1, background: 'var(--line)' }} />
    </div>
  )
}

export const FIX: Record<FixCategory, { short: string; long: string; color: string; cls: string }> = {
  pqs_icelined: { short: '(i) PQS ice-lined fridge', long: 'A PQS mains ice-lined fridge on the grid it has', color: '#3D7BD9', cls: 's-grid' },
  pqs_sdd: { short: '(ii) PQS solar fridge', long: 'A PQS solar direct-drive fridge on its own array', color: '#E8A33D', cls: 's-sun' },
  solar_clinic: { short: '(iii) Solar fridge + clinic system', long: 'A PQS solar fridge plus the separate clinic system', color: '#2FA37A', cls: 's-cell' },
}
export function FixTag({ fix }: { fix: FixCategory }) {
  return <span className={`tag ${FIX[fix].cls} fix-chip`}><Icon name={fix === 'pqs_icelined' ? 'grid' : 'sun'} size={13} />Fix {FIX[fix].short}</span>
}

/** Every facility-level uptime figure says which fridge it assumes. The headline is a household fridge. */
export const HEADLINE_SCENARIO = 'if a household or non-PQS fridge'
export const scenarioOf = (r?: ScenarioFields | null) => { const s = r?.scenario ?? r?.uptime_scenario ?? r?.scenario_label; return s && s !== 'domestic' ? `if a ${s}` : HEADLINE_SCENARIO }

export function CappedNote({ r, short }: { r: CapFields; short?: boolean }) {
  if (!r.capped) return null
  if (short) return <span className="chip" title={r.doses_demand_uncapped ? `Uncapped demand ${num(r.doses_demand_uncapped)} doses a year` : undefined}>catchment capped at 20,000</span>
  return (
    <span className="small">
      <span className="tag s-sun">Catchment capped at 20,000 people</span>{' '}
      {r.catchment_pop != null && r.pop_above_cap != null && <>Doses are counted for 20,000 people; {num(r.pop_above_cap)} more live in the catchment{r.doses_demand_uncapped != null ? <>, so uncapped demand is {num(r.doses_demand_uncapped)} doses a year</> : null}.</>}
    </span>
  )
}

/** "Checked by eye" with who and how when the API says so; otherwise read by OCR. */
export function VerifiedNote({ v }: { v: { verified?: boolean; checked_by?: string | null; how?: string | null; verified_by?: string; verified_how?: string; verified_method?: string } }) {
  if (v.verified) {
    const by = v.checked_by ?? v.verified_by, how = v.how ?? v.verified_how ?? v.verified_method
    return <span><span className="tag tag-wrap s-cell"><Icon name="check" size={13} />Checked by eye{by ? ` by ${by}` : ''}</span>{how && <span className="small muted"> {how}.</span>}</span>
  }
  return <span className="tag tag-wrap s-unknown">Read by OCR; nobody has checked it by eye</span>
}
