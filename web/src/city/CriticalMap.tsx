import { lazy, Suspense } from 'react'
import { hasWebGL, useEffectiveTheme } from '../hooks'
import { anchor, boundsOfCoords, cityFrame, DARK_SITE, isLine, LAMP, lineCoords, plantKind, SECTOR_COLOR, type MapSite } from './mapdata'
import type { MapProps } from './CriticalMapGL'
import { share } from './format'

const GL = lazy(() => import('./CriticalMapGL'))

export function CriticalMap(props: Omit<MapProps, 'dark'>) {
  const dark = useEffectiveTheme() === 'dark'
  const gl = hasWebGL() && navigator.onLine
  return (
    <div className="cmap">
      {gl ? (
        <Suspense fallback={<FallbackPlot {...props} />}>
          <GL {...props} dark={dark} />
        </Suspense>
      ) : <FallbackPlot {...props} />}
    </div>
  )
}

const mix = (a: string, b: string, k: number) => {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
  const [x, y] = [p(a), p(b)]
  return `#${x.map((v, i) => Math.round(v * (1 - k) + y[i] * k).toString(16).padStart(2, '0')).join('')}`
}

/** No WebGL or offline: the same layers as a plain SVG plot, no basemap. */
export function FallbackPlot({ sites, corridor, selected, onSelect, focus, cut, label }: Omit<MapProps, 'dark'>) {
  const W = 800, H = 520
  const b = (focus === 'corridor' ? boundsOfCoords(lineCoords(corridor), 0.1) : null) ?? cityFrame(sites.map((s) => [s.lon, s.lat])) ?? [[12.9, 11.6], [13.4, 12.0]]
  const [[w, s], [e, n]] = b
  const k = Math.min((W - 40) / (e - w), (H - 40) / (n - s))
  const x = (lon: number) => W / 2 + (lon - (w + e) / 2) * k
  const y = (lat: number) => H / 2 - (lat - (s + n) / 2) * k
  const lines = (corridor?.features ?? []).filter(isLine)
  const path = (cs: number[][]) => cs.map((c, i) => `${i ? 'L' : 'M'}${x(c[0]).toFixed(1)} ${y(c[1]).toFixed(1)}`).join('')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" role="img" aria-label={`${label} (simplified plot, no basemap)`} preserveAspectRatio="xMidYMid slice" className="cmap-svg">
      <rect width={W} height={H} fill="var(--map-bg)" />
      {lines.map((f, i) => {
        const g = f.geometry
        const parts = g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates : []
        return parts.map((p, j) => <path key={`${i}-${j}`} d={path(p)} fill="none" stroke={cut ? 'var(--cut)' : 'var(--line330)'} strokeWidth={3} strokeDasharray={cut ? '6 8' : undefined} />)
      })}
      {(corridor?.features ?? []).map((f, i) => {
        const pk = plantKind(f), at = anchor(f)
        if (!pk || !at) return null
        return (
          <g key={`p${i}`} transform={`translate(${x(at[0])} ${y(at[1])})`}>
            <rect x={-6} y={-6} width={12} height={12} rx={3} fill={pk === 'gas' ? 'var(--grid-500)' : 'var(--sun-500)'} />
            {pk !== 'battery' && <text x={10} y={4} fontSize="12" fill="var(--text)" fontFamily="var(--sans)">{pk === 'gas' ? 'MEPP gas plant' : 'UMTH solar: existing, outside the plan'}</text>}
          </g>
        )
      })}
      {sites.map((st: MapSite) => {
        const r = Math.max(3, Math.min(13, 3 + Math.sqrt(Math.max(0.1, st.kw)) * 2.4))
        return (
          <g key={st.id} onClick={() => onSelect(st.id)} style={{ cursor: 'pointer' }}>
            <title>{`${st.name}: critical hours kept today ${share(st.today)}, with the plan ${share(st.withPlan)}`}</title>
            {st.glow > 0.02 && <circle cx={x(st.lon)} cy={y(st.lat)} r={r * 2.4} fill={LAMP} opacity={0.18 * st.glow} />}
            <circle cx={x(st.lon)} cy={y(st.lat)} r={r} fill={mix(DARK_SITE, LAMP, st.glow)} stroke={st.id === selected ? 'var(--text)' : SECTOR_COLOR[st.sector]} strokeWidth={st.id === selected ? 3 : 2} />
          </g>
        )
      })}
      <text x={W - 12} y={H - 12} textAnchor="end" fontSize="11" fill="var(--muted)" fontFamily="var(--mono)">Simplified view: no basemap</text>
    </svg>
  )
}

