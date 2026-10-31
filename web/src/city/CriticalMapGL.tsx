// Lazy chunk: maplibre-gl. Critical sites as lamps (fill = share of critical hours kept, ring = sector), the 330 kV
// corridor as the single point of failure, MEPP and the existing UNIMAID/UMTH solar plant as labelled markers.
import { AttributionControl, Map as MLMap, Marker, NavigationControl, Popup, setWorkerUrl, type GeoJSONSource } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import type { FeatureCollection } from 'geojson'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import type { CorridorFC } from '../api/brief13'
import { anchor, boundsOfCoords, cityFrame, DARK_SITE, isLine, kindOf, kvOf, LAMP, lineCoords, plantKind, SECTOR_COLOR, type Bounds, type MapSite } from './mapdata'
import { SECTOR_NAME, share } from './format'

setWorkerUrl(workerUrl)

export interface MapProps {
  sites: MapSite[]; corridor: CorridorFC | null; selected: string | null; onSelect: (id: string) => void
  focus: 'city' | 'corridor'; cut: boolean; dark: boolean; label: string; reduced: boolean
}

function sitesFC(sites: MapSite[]): FeatureCollection {
  return { type: 'FeatureCollection', features: sites.map((s) => ({ type: 'Feature', properties: { id: s.id, name: s.name, kw: s.kw, ring: SECTOR_COLOR[s.sector] }, geometry: { type: 'Point', coordinates: [s.lon, s.lat] } })) }
}
const cityBounds = (sites: MapSite[]): Bounds | null => cityFrame(sites.map((s) => [s.lon, s.lat]))

export default function CriticalMapGL({ sites, corridor, selected, onSelect, focus, cut, dark, label, reduced }: MapProps) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const ready = useRef(false)
  const latest = useRef({ sites, corridor, selected, cut, focus })
  const markers = useRef<Marker[]>([])
  const [failed, setFailed] = useState(false)
  const [loaded, setLoaded] = useState(false)
  latest.current = { sites, corridor, selected, cut, focus }

  const paintGlow = (m: MLMap) => {
    // the map can be mid-teardown or mid-style-reload when React repaints
    if (!m.style || !m.getSource('sites')) return
    for (const s of latest.current.sites) m.setFeatureState({ source: 'sites', id: s.id }, { glow: s.glow, sel: s.id === latest.current.selected })
  }
  const paintCut = (m: MLMap) => {
    const c = latest.current.cut
    if (!m.getLayer('line-hi')) return
    m.setPaintProperty('line-hi', 'line-color', c ? '#E5533D' : '#5B8FE6')
    m.setPaintProperty('line-hi', 'line-dasharray', c ? [1.2, 1.6] : [1, 0])
    m.setPaintProperty('line-glow', 'line-color', c ? '#E5533D' : '#5B8FE6')
    m.setPaintProperty('line-glow', 'line-opacity', c ? 0.35 : 0.22)
  }

  useEffect(() => {
    if (!el.current) return
    let m: MLMap
    const start = (latest.current.focus === 'corridor' ? boundsOfCoords(lineCoords(latest.current.corridor), 0.1) : null) ?? cityBounds(latest.current.sites) ?? [[12.9, 11.6], [13.4, 12.0]]
    try {
      m = new MLMap({
        container: el.current, style: `https://tiles.openfreemap.org/styles/${dark ? 'dark' : 'positron'}`,
        bounds: start, fitBoundsOptions: { padding: 40 }, attributionControl: false,
        pixelRatio: Math.min(window.devicePixelRatio || 1, 2), pitch: 0, maxPitch: 60, cooperativeGestures: false,
        // keep the frame readable for screen capture (demo recording, headless checks)
        canvasContextAttributes: { preserveDrawingBuffer: true, antialias: true },
      })
    } catch { setFailed(true); return }
    map.current = m
    m.addControl(new AttributionControl({ compact: true }), 'bottom-right')
    m.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    const add = () => {
      if (m.getSource('sites')) return
      const c = latest.current.corridor
      const lines: FeatureCollection = { type: 'FeatureCollection', features: (c?.features ?? []).filter(isLine).map((f) => ({ ...f, properties: { ...f.properties, kv: kvOf(f) ?? 0 } })) }
      const towers: FeatureCollection = { type: 'FeatureCollection', features: (c?.features ?? []).filter((f) => /tower|pole/.test(kindOf(f)) && f.geometry.type === 'Point') }
      const subs: FeatureCollection = { type: 'FeatureCollection', features: (c?.features ?? []).filter((f) => /substation/.test(kindOf(f))).map((f) => ({ type: 'Feature', properties: f.properties, geometry: { type: 'Point', coordinates: anchor(f) ?? [0, 0] } })) }
      m.addSource('lines', { type: 'geojson', data: lines })
      m.addSource('towers', { type: 'geojson', data: towers })
      m.addSource('subs', { type: 'geojson', data: subs })
      m.addLayer({ id: 'line-lo', type: 'line', source: 'lines', filter: ['<', ['get', 'kv'], 300], paint: { 'line-color': dark ? '#55657E' : '#8D99AB', 'line-width': 1.4, 'line-opacity': 0.8 } })
      m.addLayer({ id: 'line-glow', type: 'line', source: 'lines', filter: ['>=', ['get', 'kv'], 300], paint: { 'line-color': '#5B8FE6', 'line-width': 10, 'line-blur': 6, 'line-opacity': 0.22 } })
      m.addLayer({ id: 'line-hi', type: 'line', source: 'lines', filter: ['>=', ['get', 'kv'], 300], layout: { 'line-cap': 'butt' }, paint: { 'line-color': '#5B8FE6', 'line-width': 3 } })
      m.addLayer({ id: 'towers', type: 'circle', source: 'towers', minzoom: 8, paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 1, 13, 3], 'circle-color': dark ? '#9AA6B8' : '#5C6675', 'circle-opacity': 0.8 } })
      m.addLayer({ id: 'subs', type: 'circle', source: 'subs', paint: { 'circle-radius': 5, 'circle-color': dark ? '#10141B' : '#FFFFFF', 'circle-stroke-color': '#5B8FE6', 'circle-stroke-width': 2 } })
      m.addSource('sites', { type: 'geojson', data: sitesFC(latest.current.sites), promoteId: 'id' })
      const r = ['interpolate', ['linear'], ['sqrt', ['max', ['get', 'kw'], 0.1]], 0, 3, 2, 6, 5, 12] as unknown as number
      m.addLayer({ id: 'site-halo', type: 'circle', source: 'sites', paint: { 'circle-radius': ['*', r, 2.6] as unknown as number, 'circle-color': LAMP, 'circle-blur': 1, 'circle-opacity': ['*', 0.55, ['coalesce', ['feature-state', 'glow'], 1]] as unknown as number } })
      m.addLayer({
        id: 'site', type: 'circle', source: 'sites',
        paint: {
          'circle-radius': r,
          'circle-color': ['interpolate', ['linear'], ['coalesce', ['feature-state', 'glow'], 1], 0, DARK_SITE, 0.5, '#9C7A35', 1, LAMP] as unknown as string,
          'circle-stroke-color': ['case', ['boolean', ['feature-state', 'sel'], false], dark ? '#FFFFFF' : '#1B1F24', ['get', 'ring']] as unknown as string,
          'circle-stroke-width': ['case', ['boolean', ['feature-state', 'sel'], false], 3, 2] as unknown as number,
        },
      })
      // plants as labelled markers (HTML, so the label is real text)
      markers.current.forEach((x) => x.remove()); markers.current = []
      for (const f of c?.features ?? []) {
        const k = plantKind(f), at = anchor(f)
        if (!k || !at) continue
        const node = document.createElement('div')
        node.className = `plant-mk ${k}`
        if (k === 'battery') { node.innerHTML = '<span class="pm-dot" aria-hidden="true"></span>'; node.title = 'UNIMAID battery plant (mapped): existing, not part of our plan' }
        else {
          // short tags so they never hide sites; the legend under the map carries the full wording
          node.innerHTML = `<span class="pm-dot" aria-hidden="true"></span><span class="pm-txt"></span>`
          ;(node.querySelector('.pm-txt') as HTMLElement).textContent = k === 'gas' ? 'MEPP gas plant' : 'UMTH solar: existing, not in plan'
          node.title = k === 'gas' ? 'Maiduguri Emergency Power Plant (MEPP): gas by road tanker; the plan works alongside it' : 'UNIMAID/UMTH solar plant: existing on-site solar, not part of our plan'
        }
        // labels lean away from the city (gas up, solar down) so they do not sit on the sites
        markers.current.push(new Marker({ element: node, anchor: 'left', offset: k === 'gas' ? [-7, -22] : k === 'solar' ? [-7, 22] : [-5, 0] }).setLngLat(at).addTo(m))
      }
      ready.current = true
      paintGlow(m); paintCut(m)
      setLoaded(true)
    }
    m.on('load', add)
    m.on('click', 'site', (e) => { const id = e.features?.[0]?.properties?.id; if (id) onSelect(String(id)) })
    const pop = new Popup({ closeButton: false, closeOnClick: false, offset: 12, className: 'site-pop', maxWidth: '260px' })
    m.on('mousemove', 'site', (e) => {
      m.getCanvas().style.cursor = 'pointer'
      const id = e.features?.[0]?.properties?.id
      const s = latest.current.sites.find((x) => x.id === id)
      if (!s) return
      const el = document.createElement('div')
      const b = document.createElement('b'); b.textContent = s.name
      const t = document.createElement('span'); t.textContent = `${SECTOR_NAME[s.sector] ?? s.sector}${s.kw ? ` · ${s.kw} kW` : ''}`
      const k = document.createElement('span'); k.textContent = `critical hours kept: today ${share(s.today)}, with the plan ${share(s.withPlan)}`
      el.append(b, t, k)
      pop.setLngLat([s.lon, s.lat]).setDOMContent(el).addTo(m)
    })
    m.on('mouseleave', 'site', () => { m.getCanvas().style.cursor = ''; pop.remove() })
    m.on('error', () => {})
    return () => { ready.current = false; markers.current.forEach((x) => x.remove()); m.remove(); map.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark, corridor])

  // new city: new site set
  const sig = sites.map((s) => s.id).join('|')
  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    ;(m.getSource('sites') as GeoJSONSource | undefined)?.setData(sitesFC(sites))
    const b = cityBounds(sites)
    if (b && latest.current.focus === 'city') m.fitBounds(b, { padding: 40, duration: reduced ? 0 : 700 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig])

  useEffect(() => { const m = map.current; if (m && ready.current) paintGlow(m) })
  useEffect(() => { const m = map.current; if (m && ready.current) paintCut(m) }, [cut, loaded])
  useEffect(() => {
    const m = map.current
    if (!m || !loaded) return
    const b = focus === 'corridor' ? boundsOfCoords(lineCoords(latest.current.corridor), 0.1) : cityBounds(latest.current.sites)
    if (b) m.fitBounds(b, { padding: 40, duration: reduced ? 0 : 1600, essential: true })
  }, [focus, loaded, reduced])

  if (failed) return null
  // inline: maplibre's own stylesheet sets .maplibregl-map to position: relative, which would collapse a class rule
  return <div ref={el} className="cmap-gl" style={{ position: 'absolute', inset: 0 }} role="region" aria-label={label} />
}
