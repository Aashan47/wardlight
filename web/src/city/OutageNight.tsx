// One site's simulated outage, from GET /api/sites/{id}/outage_trace?days= (any sector). Every site gets the
// day-by-hour strip (each row a day of the cut, each cell an hour: lit when the critical load is served) and the
// 24-hour ring for one night. A health site also gets the 3D night clinic. Today and with the plan come from the trace;
// nothing here is computed except which hours to draw.
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { b13 } from '../api/brief13-client'
import type { DataSource, SiteProps, SiteTrace } from '../api/brief13'
import type { HourlyTrace, RoomKey } from '../api/types'
import { Ring24, RingLegend } from '../components/charts'
import { Icon, Status } from '../components/ui'
import { hh } from '../format'
import { hasWebGL, useReducedMotion } from '../hooks'
import { Segmented, SourceBadge } from './bits'
import { full } from './format'

const NightClinic = lazy(() => import('../three/NightClinic'))
const ROOMS: RoomKey[] = ['fridge', 'delivery', 'oxygen', 'lab', 'ward']
const NAMES: Record<RoomKey, string> = { fridge: 'Vaccine fridge', delivery: 'Delivery room', oxygen: 'Oxygen', lab: 'Laboratory', ward: 'Ward' }
type View = 'today' | 'plan'

/** share of the critical load served each hour: rooms for a clinic, served_* for a pump or a cold room; null = not needed */
function servedSeries(t: SiteTrace, view: View): (number | null)[] {
  const rooms = view === 'plan' ? t.rooms : t.rooms_today
  if (rooms && Object.values(rooms).some((r) => r?.length)) {
    return t.hour.map((_, i) => {
      const xs = ROOMS.map((k) => rooms[k]?.[i]).filter((x) => x !== null && x !== undefined) as boolean[]
      return xs.length ? xs.filter(Boolean).length / xs.length : null
    })
  }
  const s = view === 'plan' ? t.served_with : t.served_today
  return t.hour.map((_, i) => (t.needed && !t.needed[i] ? null : s?.[i] ?? null))
}

/** 24 hours from 18:00 on outage night n, as the HourlyTrace the 3D clinic and the ring read */
function nightOf(t: SiteTrace, n: number, view: View): HourlyTrace | null {
  const first = t.in_outage.findIndex((x, i) => x && t.hour[i] === 18)
  if (first < 0 || first + 24 > t.hour.length) return null
  const i0 = Math.min(first + (n - 1) * 24, t.hour.length - 24)
  const sl = <T,>(a: T[] | undefined, fill: T) => (a ? a.slice(i0, i0 + 24) : Array(24).fill(fill))
  const src = view === 'plan' ? t.rooms : t.rooms_today
  const served = servedSeries(t, view).slice(i0, i0 + 24)
  const rooms = Object.fromEntries(ROOMS.map((k) => [k, src?.[k] ? sl(src[k]!, null) : served.map((x) => (x === null ? null : x >= 0.999))])) as Record<RoomKey, (boolean | null)[]>
  const plan = view === 'plan'
  return {
    start_hour: 18, hour: sl(t.hour, 0), grid_on: sl(t.grid_on, false),
    solar_kw: plan ? sl(t.solar_kw, 0) : (t.existing_array_kw ? sl(t.existing_array_kw, 0) : Array(24).fill(0)),
    load_kw: sl(t.load_kw, 0), battery_soc: plan ? sl(t.battery_soc, 0) : Array(24).fill(0),
    // the engine tracks whether the cold reserve lasts, not a temperature: held hours show the 5 °C setpoint, lost hours 10 °C
    fridge_c: rooms.fridge.map((x) => (x === false ? 10 : 5)),
    battery_kwh: plan ? t.battery_kwh : 0, pv_kwp: plan ? t.pv_kwp : 0, fridge_mode: 'shared', fridge_curve: 'illustrative', rooms,
  }
}

const LOAD_WORD: Record<string, string> = { solar_borehole: 'Borehole pump', motorized_borehole: 'Borehole pump', water_works: 'Water works', market_cold_room: 'Cold room', health_facility: 'Clinic' }

export function OutageNight({ site, days }: { site: SiteProps | undefined; days: number }) {
  const reduced = useReducedMotion()
  const webgl = hasWebGL()
  const [t, setT0] = useState<SiteTrace | null>(null)
  const [src, setSrc] = useState<DataSource | undefined>()
  const [err, setErr] = useState<string | null>(null)
  const [view, setView] = useState<View>('plan')
  const [night, setNight] = useState(1)
  const [clock, setClock] = useState(0)
  const [playing, setPlaying] = useState(false)
  const raf = useRef(0)

  useEffect(() => {
    setT0(null); setErr(null)
    if (!site) return
    let live = true
    b13.trace(site.id, days).then((r) => { if (live) { setT0(r.data); setSrc(r.src); setNight(Math.max(1, Math.ceil(days / 2))) } }, (e: Error) => live && setErr(e.message))
    return () => { live = false }
  }, [site, days])

  const isClinic = !!t?.rooms && Object.values(t.rooms).some((r) => r?.length)
  const trace = useMemo(() => (t ? nightOf(t, night, view) : null), [t, night, view])

  useEffect(() => {
    if (!playing) return
    let last = performance.now(), acc = 0
    const tick = (now: number) => {
      const dt = (now - last) / 1000; last = now
      setClock((prev) => {
        let next: number
        if (reduced) { acc += dt; if (acc < 0.6) return prev; acc = 0; next = Math.floor(prev) + 1 } else next = prev + dt * (24 / 12)
        if (next >= 23.99) { setPlaying(false); return 23.99 }
        return next
      })
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [playing, reduced])

  if (!site) return <div className="night-empty"><p className="muted">Pick a site on the map or in the list to run its outage.</p></div>
  if (err) return <div className="night-empty"><p className="muted">{err}. The outage trace runs on the live engine and for the sites the recorded files include.</p></div>
  if (!t) return <div className="night-empty"><p className="muted mono" role="status">Running {site.name}'s {days}-day outage…</p></div>

  const nights = Math.max(1, Math.floor(t.in_outage.filter(Boolean).length / 24))
  const idx = Math.min(23, Math.floor(clock))
  const hourNow = (18 + idx) % 24
  // the trace must run the plan's system; when it does not, say so rather than call it "the plan"
  // the trace must run the plan's system: when its draw keeps clearly fewer hours than the site's plan result, say so
  const sys = site.system
  const word = LOAD_WORD[site.archetype ?? t.archetype ?? ''] ?? 'Critical load'
  const kept = t.draw?.lane_hours_kept ?? t.draw?.lane_service_hours_with
  const planKept = (() => { const r = site.results; const b = r && typeof r === 'object' ? (r as Record<string, { with_h?: number | null }>)[String(days)] : undefined; return b?.with_h ?? null })()
  const mismatch = kept != null && planKept != null && kept < planKept * 0.95
  const planLabel = mismatch ? 'With the system in this trace' : 'With the plan'

  return (
    <div className="night2">
      <div className="row between" style={{ alignItems: 'center', gap: 10 }}>
        <Segmented id={`nv-${site.id}`} label="Show" value={view} onChange={setView} options={[{ value: 'today', label: 'Today, no backup' }, { value: 'plan', label: planLabel }]} />
        <span className="row" style={{ gap: 8 }}><SourceBadge src={src} />{kept != null && <span className="small muted">{view === 'plan' ? <>this draw keeps <b className="mono">{full(kept)}</b> critical hours with its system</> : null}</span>}</span>
      </div>
      {mismatch && sys && kept != null && planKept != null && (
        <p className="warn-note" role="note">This trace runs a {t.pv_kwp.toFixed(2)} kWp, {t.battery_kwh.toFixed(1)} kWh system, not the plan's outage-ready {sys.pv_kwp} kWp, {sys.battery_kwh} kWh, and its draw keeps {full(kept)} critical hours against the plan's {full(planKept)} for this site.</p>
      )}

      <div className="night">
        {isClinic ? (
          <div className="stage">
            {webgl && !reduced && trace ? (
              <Suspense fallback={<div className="loading">Loading the 3D clinic…</div>}><NightClinic trace={trace} t={clock} /></Suspense>
            ) : <img className="still" src="/stills/clinic-night.png" alt="Pre-rendered still of the cut-away clinic at night inside the 24-hour ring." />}
            <div className="hud">
              <div><div className="clock">{hh(hourNow)}</div><div style={{ opacity: 0.85 }}>Night {night} of the {days}-day cut · grid {trace?.grid_on[idx] ? 'on' : 'off'}</div></div>
              <div style={{ textAlign: 'right' }}>{view === 'plan' ? planLabel : 'Today, no backup'}</div>
            </div>
          </div>
        ) : (
          <Strip t={t} view={view} days={days} word={word} night={night} />
        )}
        <div className="night-side">
          {trace && <div style={{ display: 'flex', justifyContent: 'center' }}><Ring24 trace={trace} t={clock} size={196} /></div>}
          <RingLegend />
          <div className="row">
            <button className="btn primary" onClick={() => { if (clock >= 23.9) setClock(0); setPlaying((p) => !p) }} aria-pressed={playing}><Icon name={playing ? 'pause' : 'play'} /> {playing ? 'Pause' : 'Run the night'}</button>
            <button className="btn" onClick={() => { setPlaying(false); setClock(0) }}>Back to 18:00</button>
          </div>
          <div className="field">
            <label htmlFor={`night-n-${site.id}`}>Night <span className="mono">{night}</span> of the cut</label>
            <input id={`night-n-${site.id}`} type="range" min={1} max={nights} step={1} value={Math.min(night, nights)} onChange={(e) => { setNight(+e.target.value); setClock(0) }} />
          </div>
          <div className="field">
            <label htmlFor={`night-t-${site.id}`}>Time <span className="mono">{hh(hourNow)}</span></label>
            <input id={`night-t-${site.id}`} type="range" min={0} max={23.99} step={0.01} value={clock} onChange={(e) => { setPlaying(false); setClock(+e.target.value) }} aria-valuetext={hh(hourNow)} />
          </div>
          {trace && (
            isClinic ? (
              <ul className="rooms-mini" aria-label={`Critical rooms at ${hh(hourNow)}`}>
                {ROOMS.map((k) => { const on = trace.rooms[k][idx]; return <li key={k}><span>{t.room_names?.[k] ?? NAMES[k]}</span>{on === null ? <Status unknown>Not needed</Status> : <Status ok={on}>{on ? 'Lit' : 'Dark'}</Status>}</li> })}
              </ul>
            ) : (
              <ul className="rooms-mini" aria-label={`${word} at ${hh(hourNow)}`}>
                <li><span>{word}</span>{trace.rooms.fridge[idx] === null ? <Status unknown>Not needed</Status> : <Status ok={!!trace.rooms.fridge[idx]}>{trace.rooms.fridge[idx] ? 'Running' : 'Stopped'}</Status>}</li>
              </ul>
            )
          )}
          <p className="small muted" style={{ margin: 0 }}>{t.note ? `${t.note[0].toUpperCase()}${t.note.slice(1)}.` : ''}{isClinic ? ' Fridge temperature is illustrative.' : ` The 3D view models a clinic, so a ${word.toLowerCase()} is shown as the strip and the ring.`}</p>
        </div>
      </div>
      {isClinic && <Strip t={t} view={view} days={days} word="Critical rooms" night={night} compact />}
    </div>
  )
}

/** Day-by-hour strip: each row a day inside the cut, each cell one hour; lamp = critical load served, dark = not, blank = not needed. */
function Strip({ t, view, days, word, night, compact }: { t: SiteTrace; view: View; days: number; word: string; night: number; compact?: boolean }) {
  const served = useMemo(() => servedSeries(t, view), [t, view])
  const rows = useMemo(() => {
    const m = new Map<number, (number | null)[]>()
    t.hour_index.forEach((hi, i) => {
      if (!t.in_outage[i]) return
      const d = Math.floor(hi / 24)
      if (!m.has(d)) m.set(d, Array(24).fill(undefined))
      m.get(d)![hi % 24] = served[i]
    })
    return [...m.values()]
  }, [t, served])
  const C = compact ? 9 : 14, G = 2, W = 24 * (C + G), H = rows.length * (C + G)
  const firstNightRow = Math.min(rows.length - 1, night - 1)
  return (
    <figure className={`strip${compact ? ' compact' : ''}`}>
      <figcaption className="row between">
        <span><b>{word}, hour by hour through the {days}-day cut</b> <span className="small muted">{view === 'plan' ? 'with the system in the trace' : 'today, no backup'}</span></span>
        <span className="strip-key small muted"><i className="k on" />served <i className="k part" />partly <i className="k off" />not served <i className="k na" />not needed</span>
      </figcaption>
      <div className="strip-scroll">
        <svg viewBox={`-28 -16 ${W + 30} ${H + 18}`} width={W + 30} height={H + 18} role="img" aria-label={`${word}: ${rows.length} days of the cut, each row a day and each cell an hour; lit cells are hours the critical load is served`}>
          {[0, 6, 12, 18].map((h) => <text key={h} x={h * (C + G) + C / 2} y={-5} textAnchor="middle" fontSize="9" fill="var(--muted)" fontFamily="var(--mono)">{String(h).padStart(2, '0')}</text>)}
          {rows.map((r, y) => (
            <g key={y}>
              {(y === 0 || (y + 1) % 10 === 0) && <text x={-6} y={y * (C + G) + C - 1} textAnchor="end" fontSize="9" fill="var(--muted)" fontFamily="var(--mono)">{y + 1}</text>}
              {r.map((v, x) => v === undefined ? null : (
                <rect key={x} x={x * (C + G)} y={y * (C + G)} width={C} height={C} rx={2}
                  className={v === null ? 'c-na' : v >= 0.999 ? 'c-on' : v > 0.001 ? 'c-part' : 'c-off'} />
              ))}
              {y === firstNightRow && <rect x={-2} y={y * (C + G) - 2} width={W + 2} height={C + 4} fill="none" stroke="var(--text)" strokeWidth={1} rx={3} opacity={0.5} />}
            </g>
          ))}
        </svg>
      </div>
    </figure>
  )
}
