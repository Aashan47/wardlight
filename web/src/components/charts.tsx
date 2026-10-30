import type { CostPoint, HourlyTrace } from '../api/types'
import { MODE } from '../api/client'
import { hh, pct, usd } from '../format'

const TAU = Math.PI * 2
const arc = (cx: number, cy: number, r: number, h0: number, h1: number) => {
  const a0 = (h0 / 24) * TAU - Math.PI / 2, a1 = (h1 / 24) * TAU - Math.PI / 2
  const large = h1 - h0 > 12 ? 1 : 0
  return `M${cx + r * Math.cos(a0)} ${cy + r * Math.sin(a0)} A${r} ${r} 0 ${large} 1 ${cx + r * Math.cos(a1)} ${cy + r * Math.sin(a1)}`
}

/** The 24-hour ring: grid blocks (outer), sun (middle), battery level (inner), and the clock hand. */
export function Ring24({ trace, t, size = 240 }: { trace: HourlyTrace; t: number; size?: number }) {
  const c = 120, idx = Math.min(23, Math.max(0, Math.floor(t)))
  const clock = (trace.start_hour + t) % 24
  const maxSolar = Math.max(0.01, ...trace.solar_kw)
  const soc = trace.battery_soc[idx]
  const handA = (clock / 24) * TAU - Math.PI / 2
  return (
    <svg viewBox="0 0 240 240" width={size} height={size} role="img" aria-label={`24-hour ring at ${hh(clock)}: grid ${trace.grid_on[idx] ? 'on' : 'off'}, battery ${pct(soc)}`}>
      <circle cx={c} cy={c} r={104} fill="none" stroke="var(--line)" strokeWidth={14} opacity={0.5} />
      {trace.hour.map((h, i) => (
        <path key={`g${i}`} d={arc(c, c, 104, h + 0.06, h + 0.94)} stroke={trace.grid_on[i] ? 'var(--grid-500)' : 'transparent'} strokeWidth={14} fill="none" opacity={i <= idx ? 1 : 0.35} />
      ))}
      {trace.hour.map((h, i) => trace.solar_kw[i] > 0 && (
        <path key={`s${i}`} d={arc(c, c, 86, h + 0.06, h + 0.94)} stroke="var(--sun-500)" strokeWidth={10} fill="none" opacity={(0.25 + 0.75 * trace.solar_kw[i] / maxSolar) * (i <= idx ? 1 : 0.45)} />
      ))}
      <circle cx={c} cy={c} r={70} fill="none" stroke="var(--line)" strokeWidth={8} opacity={0.6} />
      {trace.battery_kwh > 0 && soc > 0.001 && <path d={arc(c, c, 70, 0, Math.min(23.99, soc * 24))} stroke="var(--cell-500)" strokeWidth={8} fill="none" />}
      {[0, 6, 12, 18].map((h) => {
        const a = (h / 24) * TAU - Math.PI / 2
        return <text key={h} x={c + 54 * Math.cos(a)} y={c + 54 * Math.sin(a) + 4} textAnchor="middle" fontSize="10" fontFamily="var(--mono)" fill="var(--muted)">{String(h).padStart(2, '0')}</text>
      })}
      <line x1={c} y1={c} x2={c + 112 * Math.cos(handA)} y2={c + 112 * Math.sin(handA)} stroke="var(--text)" strokeWidth={2} strokeLinecap="round" />
      <circle cx={c} cy={c} r={4} fill="var(--text)" />
      <text x={c} y={c + 28} textAnchor="middle" fontSize="15" fontWeight="600" fontFamily="var(--mono)" fill="var(--text)">{hh(clock)}</text>
    </svg>
  )
}

export function RingLegend() {
  const sw = (bg: string) => <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 3, background: bg, verticalAlign: '-2px', marginRight: 5 }} />
  return (
    <p className="small muted" style={{ margin: 0 }}>
      {sw('var(--grid-500)')}grid on (outer) &nbsp; {sw('var(--sun-500)')}sun (middle) &nbsp; {sw('var(--cell-500)')}battery charge (inner)
    </p>
  )
}

/** Fridge interior temperature against the 2 to 8 °C band. */
export function TempChart({ trace, t }: { trace: HourlyTrace; t: number }) {
  const W = 520, H = 170, L = 34, R = 24, T = 12, B = 26
  const x = (i: number) => L + (i / 23) * (W - L - R)
  const y = (c: number) => T + (1 - c / 14) * (H - T - B)
  const pts = trace.fridge_c.map((c, i) => `${x(i)},${y(c)}`).join(' ')
  const idx = Math.min(23, Math.max(0, Math.floor(t)))
  const cur = trace.fridge_c[idx]
  const out = cur > 8 || cur < 2
  const first = trace.fridge_c.findIndex((c) => c > 8)
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Fridge temperature over the night. At ${hh(trace.start_hour + idx)} it is ${cur.toFixed(1)} °C${first >= 0 ? `; it first leaves the 2 to 8 °C band at ${hh(trace.start_hour + first)}` : '; it stays inside 2 to 8 °C all night'}.`}>
        <rect x={L} y={y(8)} width={W - L - R} height={y(2) - y(8)} fill="var(--cell-500)" opacity={0.14} />
        <line x1={L} x2={W - R} y1={y(8)} y2={y(8)} stroke="var(--t-risk)" strokeDasharray="4 4" strokeWidth={1} />
        <line x1={L} x2={W - R} y1={y(2)} y2={y(2)} stroke="var(--t-grid)" strokeDasharray="4 4" strokeWidth={1} />
        {[0, 2, 8, 14].map((c) => <text key={c} x={L - 6} y={y(c) + 4} textAnchor="end" fontSize="10" fontFamily="var(--mono)" fill="var(--muted)">{c}°</text>)}
        {[0, 6, 12, 18, 23].map((i) => <text key={i} x={x(i)} y={H - 8} textAnchor="middle" fontSize="10" fontFamily="var(--mono)" fill="var(--muted)">{hh(trace.start_hour + i)}</text>)}
        <text x={W - R - 4} y={y(8) - 4} textAnchor="end" fontSize="10" fill="var(--t-risk)" fontFamily="var(--mono)">8 °C</text>
        <text x={W - R - 4} y={y(2) + 12} textAnchor="end" fontSize="10" fill="var(--t-grid)" fontFamily="var(--mono)">2 °C</text>
        <polyline points={pts} fill="none" stroke="var(--text)" strokeWidth={2} opacity={0.35} />
        <polyline points={trace.fridge_c.slice(0, idx + 1).map((c, i) => `${x(i)},${y(c)}`).join(' ')} fill="none" stroke={out ? 'var(--t-risk)' : 'var(--t-cell)'} strokeWidth={2.5} />
        <circle cx={x(idx)} cy={y(cur)} r={5} fill={out ? 'var(--t-risk)' : 'var(--t-cell)'} />
        <line x1={x(idx)} x2={x(idx)} y1={T} y2={H - B} stroke="var(--muted)" strokeWidth={1} opacity={0.5} />
      </svg>
      <figcaption className="small muted">
        Fridge interior (illustrative), <strong className="mono">{cur.toFixed(1)} °C</strong> at {hh(trace.start_hour + idx)}. {MODE === 'fixture' ? 'Illustrative thermal curve from sample data, not a PQS holdover figure.' : 'Illustrative: the engine tracks whether the cold reserve lasts, not a temperature, so held hours show its 5 °C setpoint and failed hours its 10 °C PQS holdover end point.'}
      </figcaption>
    </figure>
  )
}

/** Cost against battery size, with the fridge survival probability and the knee marked. */
export function CostCurve({ points, chosen }: { points: CostPoint[]; chosen: number }) {
  const W = 520, H = 190, L = 54, R = 46, T = 14, B = 30
  const maxC = Math.max(...points.map((p) => p.cost_usd), 1)
  const maxB = Math.max(...points.map((p) => p.battery_kwh), 1)
  const x = (b: number) => L + (b / maxB) * (W - L - R)
  const yc = (c: number) => T + (1 - c / maxC) * (H - T - B)
  const yp = (p: number) => T + (1 - p) * (H - T - B)
  const knee = points.find((p) => p.p_fridge.lo >= 0.9) ?? points[points.length - 1]
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Cost rises with battery size; fridge survival reaches its target at ${knee.battery_kwh} kWh for ${usd(knee.cost_usd)}.`}>
        <path d={`M${points.map((p) => `${x(p.battery_kwh)},${yp(p.p_fridge.hi)}`).join(' L')} L${[...points].reverse().map((p) => `${x(p.battery_kwh)},${yp(p.p_fridge.lo)}`).join(' L')} Z`} fill="var(--cell-500)" opacity={0.15} />
        <polyline points={points.map((p) => `${x(p.battery_kwh)},${yp(p.p_fridge.p)}`).join(' ')} fill="none" stroke="var(--t-cell)" strokeWidth={2.5} />
        <polyline points={points.map((p) => `${x(p.battery_kwh)},${yc(p.cost_usd)}`).join(' ')} fill="none" stroke="var(--t-sun)" strokeWidth={2.5} strokeDasharray="6 4" />
        {points.map((p) => <circle key={p.battery_kwh} cx={x(p.battery_kwh)} cy={yc(p.cost_usd)} r={p.battery_kwh === chosen ? 6 : 3} fill="var(--t-sun)" />)}
        <line x1={x(knee.battery_kwh)} x2={x(knee.battery_kwh)} y1={T} y2={H - B} stroke="var(--text)" strokeDasharray="2 3" />
        <text x={x(knee.battery_kwh) + 5} y={T + 10} fontSize="10" fontFamily="var(--mono)" fill="var(--text)">knee</text>
        {points.map((p) => <text key={`l${p.battery_kwh}`} x={x(p.battery_kwh)} y={H - 10} textAnchor="middle" fontSize="10" fontFamily="var(--mono)" fill="var(--muted)">{p.battery_kwh}</text>)}
        <text x={L - 6} y={T + 8} textAnchor="end" fontSize="10" fontFamily="var(--mono)" fill="var(--t-cell)">100%</text>
        <text x={L - 6} y={H - B} textAnchor="end" fontSize="10" fontFamily="var(--mono)" fill="var(--t-cell)">0%</text>
        <text x={W - R + 6} y={T + 8} fontSize="10" fontFamily="var(--mono)" fill="var(--t-sun)">${Math.round(maxC / 1000)}k</text>
        <text x={W - R + 6} y={H - B} fontSize="10" fontFamily="var(--mono)" fill="var(--t-sun)">$0</text>
      </svg>
      <figcaption className="small muted">Battery kWh (x axis). Solid: share of nights the fridge survives, with interval. Dashed: system cost.{MODE === 'fixture' ? ' Sample data.' : ''}</figcaption>
    </figure>
  )
}
