import { useEffect, useRef, useState } from 'react'
import type { HourlyTrace, RoomKey } from '../api/types'
import { createClinic, type ClinicHandle } from './scene'

const SHORT: Record<RoomKey, string> = { fridge: '1 Fridge', delivery: '2 Delivery', oxygen: '3 Oxygen', lab: '4 Lab', ward: '5 Ward' }

/** Lazy chunk: three.js lives only here. Renders on demand; nothing is drawn while off-screen. */
export default function NightClinic({ trace, t }: { trace: HourlyTrace; t: number }) {
  const wrap = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const clinic = useRef<ClinicHandle | null>(null)
  const visible = useRef(true)
  const latest = useRef({ trace, t })
  const [labels, setLabels] = useState<{ key: RoomKey; x: number; y: number }[]>([])
  const [failed, setFailed] = useState(false)
  latest.current = { trace, t }

  useEffect(() => {
    if (!canvas.current || !wrap.current) return
    let h: ClinicHandle
    try { h = createClinic(canvas.current) } catch { setFailed(true); return }
    clinic.current = h
    const relabel = () => setLabels(h.labels())
    h.onChange(relabel)
    const el = wrap.current
    const size = () => { h.resize(el.clientWidth, el.clientHeight); h.update(latest.current.trace, latest.current.t); relabel() }
    const ro = new ResizeObserver(size); ro.observe(el)
    const io = new IntersectionObserver(([e]) => {
      visible.current = e.isIntersecting
      if (e.isIntersecting) h.update(latest.current.trace, latest.current.t)
    })
    io.observe(el)
    size()
    return () => { ro.disconnect(); io.disconnect(); h.dispose(); clinic.current = null }
  }, [])

  useEffect(() => {
    if (clinic.current && visible.current && !document.hidden) clinic.current.update(trace, t)
  }, [trace, t])

  if (failed) return <div className="loading">3D view could not start on this device. The ring and the chart below show the same night.</div>

  const idx = Math.min(23, Math.max(0, Math.floor(t)))
  return (
    <div ref={wrap} style={{ position: 'absolute', inset: 0 }}>
      <canvas ref={canvas} tabIndex={0} aria-label="3D cut-away clinic at night. Drag to orbit; the controls below drive the same night." />
      {(wrap.current?.clientWidth ?? 0) >= 560 && labels.map((l) => {
        const on = trace.rooms[l.key][idx]
        return (
          <span key={l.key} className={`lbl${on === false ? ' dark' : ''}`} style={{ left: l.x, top: l.y }} aria-hidden="true">
            {SHORT[l.key]}: {on ? 'lit' : on === false ? 'dark' : 'idle'}
          </span>
        )
      })}
    </div>
  )
}
