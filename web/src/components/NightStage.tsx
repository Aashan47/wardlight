import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { api, MODE } from '../api/client'
import type { FacilityRecord, FridgeMode, HourlyTrace, LoadSurvival, RoomKey, SimulateResponse, TraceDraw } from '../api/types'
import { hasWebGL, useReducedMotion } from '../hooks'
import { hh, pct, usd } from '../format'
import { Ring24, RingLegend, TempChart } from './charts'
import { Icon, SampleBadge, Status } from './ui'

const NightClinic = lazy(() => import('../three/NightClinic'))
const ROOMS: { key: RoomKey; name: string }[] = [
  { key: 'fridge', name: 'Vaccine fridge' }, { key: 'delivery', name: 'Delivery room' }, { key: 'oxygen', name: 'Oxygen' },
  { key: 'lab', name: 'Laboratory' }, { key: 'ward', name: 'Ward' },
]

export function NightStage({ id, record }: { id: string; record: FacilityRecord }) {
  const reduced = useReducedMotion()
  const webgl = hasWebGL()
  const [want3d, setWant3d] = useState(false)
  const show3d = webgl && (!reduced || want3d)
  const [trace, setTrace] = useState<HourlyTrace>(record.trace!)
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [steps, setSteps] = useState<{ pv_kwp: number[]; battery_kwh: number[] } | null>(null)
  const [pv, setPv] = useState(0)
  const [bat, setBat] = useState(0)
  const [mode, setMode] = useState<FridgeMode>('shared')
  const [sim, setSim] = useState<SimulateResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const raf = useRef(0)

  useEffect(() => { api.simulateSteps(id).then(setSteps).catch(() => setSteps(null)) }, [id])

  // what-if: call simulate when a slider or the fridge design changes (debounced)
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    let live = true
    setBusy(true)
    const h = setTimeout(() => {
      api.simulate(id, { loads: ROOMS.map((r) => r.key), pv_kwp: pv, battery_kwh: bat, target: 0.99, fridge_mode: mode })
        .then((r) => { if (live) { setSim(r); setTrace(r.trace) } })
        .catch(() => {})
        .finally(() => live && setBusy(false))
    }, 120)
    return () => { live = false; clearTimeout(h) }
  }, [id, pv, bat, mode])

  // Run the night: 24 hours in about 14 s, or hour by hour when reduced motion is on
  useEffect(() => {
    if (!playing) return
    let last = performance.now(), acc = 0
    const tick = (now: number) => {
      const dt = (now - last) / 1000; last = now
      setT((prev) => {
        let next: number
        if (reduced) { acc += dt; if (acc < 0.7) return prev; acc = 0; next = Math.floor(prev) + 1 }
        else next = prev + dt * (24 / 14)
        if (next >= 23.99) { setPlaying(false); return 23.99 }
        return next
      })
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [playing, reduced])

  const idx = Math.min(23, Math.floor(t))
  const clock = (trace.start_hour + idx) % 24
  const firstDark = trace.rooms.fridge.findIndex((x) => x === false)
  const firstWarm = trace.fridge_c.findIndex((c) => c > 8)
  const fridgeSurv: LoadSurvival | undefined = (sim?.survival ?? record.survival_today)?.find((s) => s.load === 'fridge')
  const pvSteps = steps?.pv_kwp, batSteps = steps?.battery_kwh
  const soc = trace.battery_kwh > 0 ? trace.battery_soc[idx] : 0

  return (
    <div className="stack">
      <div className="grid2 wide-left">
        <div className="stage" aria-describedby="night-desc">
          {show3d ? (
            <Suspense fallback={<div className="loading">Loading the 3D clinic…</div>}>
              <NightClinic trace={trace} t={t} />
            </Suspense>
          ) : (
            <>
              <img className="still" src="/stills/clinic-night.png" alt="Pre-rendered still of the cut-away clinic at night inside the 24-hour ring: rooftop array, battery tank and five rooms." />
              <div className="fallback-note">
                {webgl ? 'Reduced motion is on, so this is a still. ' : 'WebGL is not available, so this is a pre-rendered still. '}
                The ring and the fridge chart run the same night.
                {webgl && <> <button className="btn small" style={{ marginLeft: 6 }} onClick={() => setWant3d(true)}>Show the interactive 3D</button></>}
              </div>
            </>
          )}
          <div className="hud">
            <div><div className="clock" aria-live="off">{hh(clock)}</div><div style={{ opacity: 0.8 }}>{trace.grid_on[idx] ? 'Grid on' : 'Grid off'} · battery {trace.battery_kwh > 0 ? pct(soc) : 'none'}</div></div>
            <div style={{ textAlign: 'right' }}>{MODE === 'fixture' && <SampleBadge />}</div>
          </div>
        </div>
        <div className="card stack">
          <div className="row between">
            <h3 style={{ margin: 0 }}>The night, hour by hour</h3>
          </div>
          <div style={{ display: 'flex', justifyContent: 'center' }}><Ring24 trace={trace} t={t} size={220} /></div>
          <RingLegend />
          <div className="row">
            <button className="btn primary" onClick={() => { if (t >= 23.9) setT(0); setPlaying((p) => !p) }} aria-pressed={playing}>
              <Icon name={playing ? 'pause' : 'play'} /> {playing ? 'Pause' : 'Run the night'}
            </button>
            <button className="btn" onClick={() => { setPlaying(false); setT(0) }}>Reset to 18:00</button>
          </div>
          <div className="field">
            <label htmlFor="scrub">Time: <span className="mono">{hh(clock)}</span></label>
            <input id="scrub" type="range" min={0} max={23.99} step={0.01} value={t} onChange={(e) => { setPlaying(false); setT(+e.target.value) }} aria-valuetext={hh(clock)} />
          </div>
        </div>
      </div>

      <p id="night-desc" className="small muted" style={{ margin: 0 }}>
        {firstDark >= 0 ? <>The fridge first loses power at <strong className="mono">{hh(trace.start_hour + firstDark)}</strong>. </> : <>The fridge keeps power all night. </>}
        {firstWarm >= 0 ? <>Its interior passes 8 °C at <strong className="mono">{hh(trace.start_hour + firstWarm)}</strong>.</> : <>Its interior stays inside 2 to 8 °C.</>}{MODE === 'fixture' ? ' One modelled night from sample data.' : ' One simulated night from the engine\'s draws for the headline scenario; which one is labelled below.'}
      </p>

      <DrawLabel trace={trace as HourlyTrace & { draw?: TraceDraw; note?: string }} />

      <div className="rooms" role="list" aria-label={`Rooms at ${hh(clock)}, in priority order`}>
        {ROOMS.map((r, i) => {
          const on = trace.rooms[r.key][idx]
          return (
            <div className="room" role="listitem" key={r.key}>
              <span className="mono muted">{i + 1}</span> {r.name}
              <span style={{ marginLeft: 'auto' }}>{on === null ? <Status unknown>Idle</Status> : <Status ok={on}>{on ? 'Lit' : 'Dark'}</Status>}</span>
            </div>
          )
        })}
      </div>

      <div className="grid2">
        <div className="card"><TempChart trace={trace} t={t} /></div>
        <div className="card stack">
          <div className="row between"><h3 style={{ margin: 0 }}>What if</h3>{busy && <span className="small muted mono" role="status">simulating…</span>}</div>
          <fieldset style={{ border: 'none', padding: 0, margin: 0 }}>
            <legend className="small" style={{ fontWeight: 500, marginBottom: 6 }}>Where the vaccine fridge gets its power</legend>
            <label className="row small" style={{ fontWeight: 400, gap: 8 }}><input type="radio" name="fm" checked={mode === 'shared'} onChange={() => setMode('shared')} /> {MODE === 'live' ? 'Today\'s fridge on the grid it has' : 'Shared clinic battery (today\'s mains fridge)'}</label>
            <label className="row small" style={{ fontWeight: 400, gap: 8 }}><input type="radio" name="fm" checked={mode === 'pqs_sdd'} onChange={() => setMode('pqs_sdd')} /> Dedicated PQS solar fridge, its own array</label>
          </fieldset>
          <Slider label="Battery" unit="kWh" value={bat} set={setBat} steps={batSteps} max={80} />
          <Slider label="Rooftop PV" unit="kWp" value={pv} set={setPv} steps={pvSteps} max={15} />
          <div className="metrics">
            <div><div className="kicker">Fridge holds 2 to 8 °C, {mode === 'pqs_sdd' ? 'PQS solar fridge' : 'household or non-PQS fridge'}</div><div className="metric" style={{ fontSize: '1.5rem' }}>{fridgeSurv ? pct(fridgeSurv.p) : 'n/a'}</div>{fridgeSurv && <div className="small muted mono">{pct(fridgeSurv.lo)} to {pct(fridgeSurv.hi)}</div>}</div>
            <div><div className="kicker">System cost</div><div className="metric" style={{ fontSize: '1.5rem' }}>{sim ? usd(sim.cost_usd) : 'n/a'}</div><div className="small muted">{MODE === 'fixture' ? 'sample cost model' : sim?.cost_usd != null ? 'clinic system at SEforALL $/Wp, plus the SDD price in PQS mode' : 'move a slider to cost a system'}</div></div>
          </div>
          <p className="small muted" style={{ margin: 0 }}>
            {mode === 'shared' ? (MODE === 'live' ? 'Today\'s fridge on the grid it has. The engine never puts a vaccine fridge on the clinic battery (WHO PQS PV01.3); the sliders size the separate clinic system for the other rooms.' : 'A shared battery is not a PQS cold-chain design: WHO PQS forbids other loads on a PQS solar fridge system.') : 'The PQS fridge runs on its own array; the sliders size the separate clinic system for the other rooms.'}
            {MODE === 'fixture' && ' Sliders step through precomputed sample runs.'}
          </p>
        </div>
      </div>
    </div>
  )
}

function Slider({ label, unit, value, set, steps, max }: { label: string; unit: string; value: number; set: (v: number) => void; steps?: number[]; max: number }) {
  const id = `sl-${label.replace(/\W/g, '')}`
  if (steps) {
    const i = Math.max(0, steps.indexOf(value))
    return (
      <div className="field">
        <div className="range-row"><label htmlFor={id}>{label}</label><output htmlFor={id}>{steps[i]} {unit}</output></div>
        <input id={id} type="range" min={0} max={steps.length - 1} step={1} value={i} onChange={(e) => set(steps[+e.target.value])} aria-valuetext={`${steps[i]} ${unit}`} />
      </div>
    )
  }
  return (
    <div className="field">
      <div className="range-row"><label htmlFor={id}>{label}</label><output htmlFor={id}>{value} {unit}</output></div>
      <input id={id} type="range" min={0} max={max} step={max > 20 ? 1 : 0.5} value={value} onChange={(e) => set(+e.target.value)} aria-valuetext={`${value} ${unit}`} />
    </div>
  )
}

/** Which scenario and which simulated draw the ring and the 3D night show (the API's own label). */
function DrawLabel({ trace }: { trace: HourlyTrace & { draw?: TraceDraw; note?: string } }) {
  const d = trace.draw
  if (!d) return null
  return (
    <div className="draw-label small">
      <strong>Scenario:</strong> {d.scenario}. <strong>Draw:</strong> lane {d.lane + 1} of {d.n_lanes}, night {d.night_index + 1} of {d.nights_in_lane} (day {d.day_of_year} of the weather year), {d.window_grid_hours} grid hours that night (the lane's median night: {d.lane_median_grid_hours} h).
      {' '}This lane holds the fridge on {pct(d.lane_uptime)} of days; the median over all draws is {pct(d.run_median_uptime)} and the headline {pct(d.headline_uptime)}.
      {' '}{d.state_matched ? `The fridge ${d.window_fridge_held ? 'holds' : 'fails'} this night, as the headline says it does on most nights.` : 'No night in this draw matched the headline, so the nearest is shown.'}
      <details style={{ marginTop: 4 }}><summary className="muted">How this night was chosen</summary><p className="muted" style={{ margin: '4px 0 0' }}>{d.rule}. {d.headline_source}. {trace.note}</p></details>
    </div>
  )
}
