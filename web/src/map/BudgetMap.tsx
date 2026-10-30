// Lazy chunk: maplibre-gl lives only here. OpenFreeMap vector tiles, facilities as 3D columns.
import { AttributionControl, Map as MLMap, NavigationControl, setWorkerUrl, type GeoJSONSource } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import type { FeatureCollection } from 'geojson'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import type { MapPoint } from './types'

setWorkerUrl(workerUrl) // the bundler moves maplibre's worker; point it at the emitted file


type B = [[number, number], [number, number]]
export function boundsOf(points: MapPoint[]): B {
  if (!points.length) return [[2.7, 4.2], [14.7, 13.9]] // Nigeria
  let w = 180, s = 90, e = -180, n = -90
  for (const p of points) { w = Math.min(w, p.lon); e = Math.max(e, p.lon); s = Math.min(s, p.lat); n = Math.max(n, p.lat) }
  const pad = 0.05
  return [[w - pad, s - pad], [e + pad, n + pad]]
}

function toGeoJSON(points: MapPoint[]): FeatureCollection {
  const d = 0.018
  return {
    type: 'FeatureCollection',
    features: points.map((p) => ({
      type: 'Feature', id: p.n,
      properties: { id: p.id, name: p.name, height: p.height, color: p.color },
      geometry: { type: 'Polygon', coordinates: [[[p.lon - d, p.lat - d], [p.lon + d, p.lat - d], [p.lon + d, p.lat + d], [p.lon - d, p.lat + d], [p.lon - d, p.lat - d]]] },
    })),
  }
}

export default function BudgetMap({ points, dark, onSelect, label }: { points: MapPoint[]; dark: boolean; onSelect?: (id: string) => void; label: string }) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const ready = useRef(false)
  const latest = useRef(points)
  const [failed, setFailed] = useState(false)
  latest.current = points

  useEffect(() => {
    if (!el.current) return
    let m: MLMap
    try {
      m = new MLMap({
        container: el.current,
        style: `https://tiles.openfreemap.org/styles/${dark ? 'dark' : 'positron'}`,
        bounds: boundsOf(latest.current), fitBoundsOptions: { padding: 24 },
        pitch: 52, bearing: -14, attributionControl: false, pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
        maxPitch: 70, cooperativeGestures: false,
      })
    } catch { setFailed(true); return }
    map.current = m
    m.addControl(new AttributionControl({ compact: false }), 'bottom-right')
    m.addControl(new NavigationControl({ visualizePitch: true }), 'top-right')
    const addLayers = () => {
      if (m.getSource('fac')) return
      m.addSource('fac', { type: 'geojson', data: toGeoJSON(latest.current) })
      m.addLayer({
        id: 'fac-col', type: 'fill-extrusion', source: 'fac',
        paint: { 'fill-extrusion-color': ['get', 'color'], 'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-opacity': 0.92, 'fill-extrusion-base': 0 },
      })
      ready.current = true
    }
    m.on('load', addLayers)
    m.on('style.load', addLayers)
    m.on('click', 'fac-col', (e) => { const id = e.features?.[0]?.properties?.id; if (id && onSelect) onSelect(id) })
    m.on('mouseenter', 'fac-col', () => { m.getCanvas().style.cursor = 'pointer' })
    m.on('mouseleave', 'fac-col', () => { m.getCanvas().style.cursor = '' })
    m.on('error', () => {})
    return () => { ready.current = false; m.remove(); map.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark])

  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    ;(m.getSource('fac') as GeoJSONSource | undefined)?.setData(toGeoJSON(points))
  }, [points])
  // a different set of facilities (another state): fly to it
  const sig = points.length ? `${points.length}:${points[0].id}` : ''
  const lastSig = useRef(sig)
  useEffect(() => {
    const m = map.current
    if (!m || sig === lastSig.current) return
    lastSig.current = sig
    m.fitBounds(boundsOf(points), { padding: 24, pitch: 52, bearing: -14, duration: 600 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig])

  if (failed) return null
  return <div ref={el} style={{ position: 'absolute', inset: 0 }} role="region" aria-label={label} />
}
