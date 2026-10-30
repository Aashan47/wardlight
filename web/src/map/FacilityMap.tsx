import { lazy, Suspense } from 'react'
import { hasWebGL, useEffectiveTheme } from '../hooks'
import { navigate } from '../router'
import type { MapPoint } from './types'

const BudgetMap = lazy(() => import('./BudgetMap'))

/** Map with 3D columns when WebGL works; an SVG column plot when it does not (offline or no WebGL). */
export function FacilityMap({ points, label, legend }: { points: MapPoint[]; label: string; legend: React.ReactNode }) {
  const dark = useEffectiveTheme() === 'dark'
  const gl = hasWebGL() && navigator.onLine
  return (
    <div className="map">
      {gl ? (
        <Suspense fallback={<FallbackMap points={points} label={label} />}>
          <BudgetMap points={points} dark={dark} label={label} onSelect={(id) => navigate(`/facility/${id}`)} />
        </Suspense>
      ) : <FallbackMap points={points} label={label} />}
      <div className="legend">{legend}</div>
    </div>
  )
}

export function FallbackMap({ points, label }: { points: MapPoint[]; label: string }) {
  const W = 640, H = 520
  const lons = points.map((p) => p.lon), lats = points.map((p) => p.lat)
  const lon0 = points.length ? Math.min(...lons) - 0.05 : 2.7, lon1 = points.length ? Math.max(...lons) + 0.05 : 14.7
  const lat0 = points.length ? Math.min(...lats) - 0.05 : 4.2, lat1 = points.length ? Math.max(...lats) + 0.05 : 13.9
  const x = (lon: number) => 30 + ((lon - lon0) / (lon1 - lon0)) * (W - 60)
  const y = (lat: number) => 40 + (1 - (lat - lat0) / (lat1 - lat0)) * (H - 80)
  const maxH = Math.max(1, ...points.map((p) => p.height))
  const sorted = [...points].sort((a, b) => b.lat - a.lat)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" role="img" aria-label={`${label} (simplified plot, no basemap)`} preserveAspectRatio="xMidYMid meet">
      <rect width={W} height={H} fill="var(--surface)" />
      {sorted.map((p) => {
        const h = 6 + (p.height / maxH) * 70
        return (
          <a key={p.id} href={`/facility/${p.id}`} onClick={(e) => { e.preventDefault(); navigate(`/facility/${p.id}`) }}>
            <title>{p.name}</title>
            <rect x={x(p.lon) - 4} y={y(p.lat) - h} width={8} height={h} fill={p.color} opacity={0.9} rx={1.5} />
            <ellipse cx={x(p.lon)} cy={y(p.lat)} rx={6} ry={2.4} fill="var(--text)" opacity={0.18} />
          </a>
        )
      })}
      <text x={W - 12} y={H - 12} textAnchor="end" fontSize="11" fill="var(--muted)" fontFamily="var(--mono)">Simplified view: no basemap (offline or no WebGL)</text>
    </svg>
  )
}
