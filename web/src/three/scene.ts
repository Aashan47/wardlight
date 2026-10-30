// The 3D night clinic. Cut-away primary health centre, rooftop array, battery tank, five rooms that
// light in priority order, standing inside the 24-hour ring. Everything it shows is read from the
// hourly trace it is given; it computes nothing itself.
import {
  AmbientLight, BoxGeometry, CircleGeometry, Color, CylinderGeometry, DirectionalLight, Group, HemisphereLight, Mesh,
  MeshBasicMaterial, MeshStandardMaterial, PerspectiveCamera, PlaneGeometry, PointLight, RingGeometry, Scene, SphereGeometry,
  Vector3, WebGLRenderer, type Material,
} from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { HourlyTrace, RoomKey } from '../api/types'

export const ROOM_ORDER: RoomKey[] = ['fridge', 'delivery', 'oxygen', 'lab', 'ward']
const ROOM_W = 1.25, DEPTH = 2.5, WALL_H = 1.45
const C = {
  night: new Color('#0E1420'), grid: new Color('#3D7BD9'), sun: new Color('#E8A33D'), cell: new Color('#2FA37A'),
  risk: new Color('#C2412D'), off: new Color('#252D3B'), wall: new Color('#D9D4C7'), floor: new Color('#8E8A80'),
}
const LIGHT_COLOR: Record<RoomKey, string> = { fridge: '#CFE6FF', delivery: '#FFE3B8', oxygen: '#E6F1FF', lab: '#F4F7FF', ward: '#FFD9A3' }

export interface ClinicHandle {
  update(trace: HourlyTrace, t: number): void
  resize(w: number, h: number): void
  render(): void
  labels(): { key: RoomKey; x: number; y: number }[]
  setDark(dark: boolean): void
  dispose(): void
  onChange(fn: () => void): void
}

export function createClinic(canvas: HTMLCanvasElement): ClinicHandle {
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false, preserveDrawingBuffer: true, powerPreference: 'low-power' })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)) // DPR capped at 2
  const scene = new Scene()
  scene.background = C.night.clone()
  const camera = new PerspectiveCamera(38, 4 / 3, 0.1, 100)
  camera.position.set(4.8, 9.6, 10.2)
  const controls = new OrbitControls(camera, canvas)
  controls.target.set(0, 0.3, 0.4)
  controls.enablePan = false
  controls.minDistance = 7
  controls.maxDistance = 20
  controls.maxPolarAngle = Math.PI * 0.46
  controls.update()

  const disposables: { dispose(): void }[] = []
  const mat = (o: ConstructorParameters<typeof MeshStandardMaterial>[0]) => { const m = new MeshStandardMaterial(o); disposables.push(m); return m }
  const box = (w: number, h: number, d: number) => { const g = new BoxGeometry(w, h, d); disposables.push(g); return g }
  const add = (g: ConstructorParameters<typeof Mesh>[0], m: Material, x: number, y: number, z: number, parent: Group | Scene = scene) => {
    const mesh = new Mesh(g, m); mesh.position.set(x, y, z); parent.add(mesh); return mesh
  }

  // lights
  const hemi = new HemisphereLight('#9fb4d6', '#1a2130', 0.6); scene.add(hemi)
  const moon = new DirectionalLight('#8fa8d8', 0.45); moon.position.set(-5, 9, 6); scene.add(moon)
  const amb = new AmbientLight('#ffffff', 0.08); scene.add(amb)
  const sunLight = new DirectionalLight('#ffe2b0', 0); scene.add(sunLight)

  // ground and ring
  const ground = add(new CircleGeometry(6.4, 72), mat({ color: '#141B28', roughness: 1 }), 0, 0, 0)
  ground.rotation.x = -Math.PI / 2
  const ringAngle = (h: number) => Math.PI / 2 - (h / 24) * Math.PI * 2
  const gridSegs: Mesh[] = [], sunSegs: Mesh[] = []
  for (let h = 0; h < 24; h++) {
    const g1 = new RingGeometry(5.05, 5.75, 6, 1, ringAngle(h + 0.95), (Math.PI * 2 / 24) * 0.9); disposables.push(g1)
    const m1 = new MeshBasicMaterial({ color: C.off.clone() }); disposables.push(m1)
    const s1 = add(g1, m1, 0, 0.02, 0); s1.rotation.x = -Math.PI / 2; gridSegs.push(s1)
    const g2 = new RingGeometry(4.45, 4.85, 6, 1, ringAngle(h + 0.95), (Math.PI * 2 / 24) * 0.9); disposables.push(g2)
    const m2 = new MeshBasicMaterial({ color: C.off.clone() }); disposables.push(m2)
    const s2 = add(g2, m2, 0, 0.02, 0); s2.rotation.x = -Math.PI / 2; sunSegs.push(s2)
  }
  // hour ticks at 00, 06, 12, 18
  for (const h of [0, 6, 12, 18]) {
    const a = ringAngle(h)
    const tick = add(box(0.06, 0.04, 0.5), new MeshBasicMaterial({ color: '#ECEAE3' }), Math.cos(a) * 6.1, 0.03, -Math.sin(a) * 6.1)
    tick.rotation.y = a
  }
  const marker = add(new SphereGeometry(0.2, 20, 14), new MeshBasicMaterial({ color: '#ffffff' }), 0, 0.25, 0)

  // building
  const clinic = new Group(); clinic.position.set(-0.4, 0, -0.2); scene.add(clinic)
  const total = ROOM_W * 5
  add(box(total + 0.3, 0.16, DEPTH + 0.3), mat({ color: C.floor, roughness: 0.9 }), 0, 0.08, 0, clinic)
  const wallM = mat({ color: C.wall, roughness: 0.85 })
  add(box(total + 0.3, WALL_H, 0.12), wallM, 0, 0.16 + WALL_H / 2, -DEPTH / 2, clinic)
  for (let i = 0; i <= 5; i++) {
    const w = add(box(0.1, WALL_H, DEPTH), wallM, -total / 2 + i * ROOM_W, 0.16 + WALL_H / 2, 0, clinic)
    if (i > 0 && i < 5) { w.scale.y = 0.8; w.position.y = 0.16 + (WALL_H * 0.8) / 2 }
  }
  // roof over the back half (cut away at the front) with the array on it
  const roofY = 0.16 + WALL_H + 0.06
  add(box(total + 0.4, 0.1, DEPTH * 0.48), mat({ color: '#B9B2A2', roughness: 0.9 }), 0, roofY, -DEPTH * 0.27, clinic)
  const panelM = mat({ color: '#2E5384', roughness: 0.4, metalness: 0, emissive: C.sun.clone(), emissiveIntensity: 0 })
  for (let i = 0; i < 6; i++) {
    const p = add(box(0.92, 0.04, 0.9), panelM, -total / 2 + 0.6 + i * 1.04, roofY + 0.22, -DEPTH * 0.27, clinic)
    p.rotation.x = -0.32
  }

  // rooms
  const rooms = {} as Record<RoomKey, { light: PointLight; glow: Mesh; glowM: MeshStandardMaterial; anchor: Vector3 }>
  const objM = mat({ color: '#E9ECEF', roughness: 0.6 })
  ROOM_ORDER.forEach((key, i) => {
    const cx = -total / 2 + ROOM_W * (i + 0.5)
    const g = new Group(); g.position.set(cx, 0.16, 0); clinic.add(g)
    const glowM = mat({ color: '#2a2f38', emissive: new Color(LIGHT_COLOR[key]), emissiveIntensity: 0, roughness: 1 })
    const glow = add(new PlaneGeometry(ROOM_W - 0.14, DEPTH - 0.14), glowM, 0, 0.01, 0, g); glow.rotation.x = -Math.PI / 2
    const light = new PointLight(LIGHT_COLOR[key], 0, 3.2, 1.6); light.position.set(0, 1.15, 0.1); g.add(light)
    // furniture that says what the room is
    if (key === 'fridge') {
      add(box(0.42, 0.95, 0.42), objM, -0.2, 0.48, -DEPTH / 2 + 0.35, g)
      add(box(0.3, 0.6, 0.3), mat({ color: '#DDE6EE' }), 0.28, 0.3, -DEPTH / 2 + 0.3, g)
    } else if (key === 'delivery') {
      add(box(0.5, 0.32, 1.0), mat({ color: '#9CC3E8' }), 0, 0.16, -0.2, g)
      add(new CylinderGeometry(0.02, 0.02, 1.0, 6), objM, 0.38, 0.5, -0.8, g)
      add(new SphereGeometry(0.1, 12, 8), mat({ color: '#FFF5E0', emissive: new Color('#FFE3B8'), emissiveIntensity: 0.2 }), 0.38, 1.0, -0.8, g)
    } else if (key === 'oxygen') {
      add(box(0.36, 0.55, 0.3), objM, -0.15, 0.28, -0.6, g)
      add(new CylinderGeometry(0.1, 0.1, 0.8, 12), mat({ color: '#3FA36E' }), 0.25, 0.4, -0.75, g)
      add(box(0.5, 0.3, 0.9), mat({ color: '#9CC3E8' }), 0.05, 0.15, 0.4, g)
    } else if (key === 'lab') {
      add(box(1.0, 0.45, 0.42), mat({ color: '#B5ADA0' }), 0, 0.23, -DEPTH / 2 + 0.3, g)
      add(new CylinderGeometry(0.05, 0.08, 0.28, 10), mat({ color: '#2B2F36' }), -0.2, 0.6, -DEPTH / 2 + 0.3, g)
      add(box(0.18, 0.2, 0.18), objM, 0.25, 0.55, -DEPTH / 2 + 0.3, g)
    } else {
      add(box(0.42, 0.26, 0.95), mat({ color: '#9CC3E8' }), -0.27, 0.13, -0.35, g)
      add(box(0.42, 0.26, 0.95), mat({ color: '#9CC3E8' }), 0.3, 0.13, 0.45, g)
    }
    rooms[key] = { light, glow, glowM, anchor: new Vector3(cx, 0.16 + WALL_H + 0.3 + (i % 2) * 0.9, DEPTH / 2) }
  })
  // the fridge's status lamp
  const fridgeLampM = new MeshBasicMaterial({ color: C.cell.clone() }); disposables.push(fridgeLampM)
  add(new SphereGeometry(0.06, 10, 8), fridgeLampM, -total / 2 + ROOM_W * 0.5 - 0.2, 0.16 + 1.02, -DEPTH / 2 + 0.58, clinic)

  // battery tank: translucent shell, fluid level from the trace
  const tank = new Group(); tank.position.set(4.0, 0, 0.9); scene.add(tank)
  const shell = add(new CylinderGeometry(0.55, 0.55, 1.8, 32, 1, true), mat({ color: '#c9d6ea', emissive: new Color('#4a5d7a'), emissiveIntensity: 0.5, transparent: true, opacity: 0.32, roughness: 0.2, depthWrite: false }), 0, 0.92, 0, tank)
  shell.renderOrder = 2
  add(new CylinderGeometry(0.6, 0.6, 0.06, 32), mat({ color: '#5a6476' }), 0, 0.03, 0, tank)
  add(new CylinderGeometry(0.6, 0.6, 0.06, 32), mat({ color: '#5a6476' }), 0, 1.83, 0, tank)
  const fluidM = mat({ color: C.cell.clone(), emissive: C.cell.clone(), emissiveIntensity: 0.35, roughness: 0.4 })
  const fluid = add(new CylinderGeometry(0.5, 0.5, 1, 32), fluidM, 0, 0.06, 0, tank)
  // grid connection: a pole and a line that glows when the feeder is on
  const pole = new Group(); pole.position.set(-4.3, 0, 1.0); scene.add(pole)
  add(new CylinderGeometry(0.06, 0.08, 2.4, 8), mat({ color: '#6b5b45' }), 0, 1.2, 0, pole)
  add(box(0.8, 0.06, 0.06), mat({ color: '#6b5b45' }), 0, 2.25, 0, pole)
  const wireM = new MeshBasicMaterial({ color: C.off.clone() }); disposables.push(wireM)
  const wire = add(new CylinderGeometry(0.03, 0.03, 1, 6), wireM, 0, 0, 0)
  const a = new Vector3(-4.3, 2.25, 1.0), b = new Vector3(-total / 2 - 0.4, roofY, -0.2)
  wire.position.copy(a.clone().add(b).multiplyScalar(0.5)); wire.scale.y = a.distanceTo(b)
  wire.quaternion.setFromUnitVectors(new Vector3(0, 1, 0), b.clone().sub(a).normalize())

  // the sun on its arc
  const sunM = new MeshBasicMaterial({ color: C.sun.clone() }); disposables.push(sunM)
  const sun = add(new SphereGeometry(0.35, 20, 14), sunM, 0, -5, 0)

  let changeFn = () => {}
  controls.addEventListener('change', () => { renderer.render(scene, camera); changeFn() })

  const handle: ClinicHandle = {
    update(trace, t) {
      const idx = Math.min(23, Math.max(0, Math.floor(t)))
      const clock = (trace.start_hour + t) % 24
      const maxSolar = Math.max(0.01, ...trace.solar_kw)
      trace.hour.forEach((h, i) => {
        const past = i <= idx ? 1 : 0.35
        ;(gridSegs[h].material as MeshBasicMaterial).color.copy(trace.grid_on[i] ? C.grid : C.off).multiplyScalar(trace.grid_on[i] ? past : 1)
        const s = trace.solar_kw[i] / maxSolar
        ;(sunSegs[h].material as MeshBasicMaterial).color.copy(C.off).lerp(C.sun, s > 0 ? (0.3 + 0.7 * s) * past : 0)
      })
      const ma = ringAngle(clock)
      marker.position.set(Math.cos(ma) * 5.4, 0.25, -Math.sin(ma) * 5.4)
      // sun: rises at 06 in the east (+x), sets at 18 in the west
      const day = (clock - 6) / 12
      const up = day > 0 && day < 1
      const sa = Math.PI * (up ? day : 0)
      sun.visible = up
      sun.position.set(Math.cos(sa) * 7.5, Math.sin(sa) * 5.5 + 0.4, -2.2)
      const solarNow = trace.solar_kw[idx] / maxSolar
      sunLight.position.copy(sun.position)
      sunLight.intensity = up ? 0.5 + 1.6 * Math.sin(sa) : 0
      hemi.intensity = up ? 0.6 + 0.6 * Math.sin(sa) : 0.55
      ;(scene.background as Color).copy(C.night).lerp(new Color('#3c5a80'), up ? 0.55 * Math.sin(sa) : 0)
      panelM.emissiveIntensity = trace.pv_kwp > 0 ? 0.6 * solarNow : 0
      const gridOn = trace.grid_on[idx]
      wireM.color.copy(gridOn ? C.grid : C.off)
      for (const key of ROOM_ORDER) {
        const on = trace.rooms[key][idx]
        const r = rooms[key]
        r.light.intensity = on ? 3.2 : on === null ? 0.25 : 0
        r.glowM.emissiveIntensity = on ? 0.55 : on === null ? 0.06 : 0
      }
      const temp = trace.fridge_c[idx]
      fridgeLampM.color.copy(temp > 8 || temp < 2 ? C.risk : C.cell)
      const soc = trace.battery_kwh > 0 ? trace.battery_soc[idx] : 0
      fluid.visible = soc > 0.005
      fluid.scale.y = Math.max(0.001, soc * 1.72)
      fluid.position.y = 0.06 + (soc * 1.72) / 2
      fluidM.color.copy(soc < 0.15 ? C.risk : C.cell); fluidM.emissive.copy(fluidM.color)
      renderer.render(scene, camera)
    },
    resize(w, h) {
      renderer.setSize(w, h, false)
      camera.aspect = w / h
      // pull back on narrow screens so the whole ring fits
      camera.fov = w / h < 1.4 ? 48 : 38
      camera.updateProjectionMatrix()
      renderer.render(scene, camera)
    },
    render() { renderer.render(scene, camera) },
    labels() {
      const w = canvas.clientWidth, h = canvas.clientHeight
      return ROOM_ORDER.map((key) => {
        const v = rooms[key].anchor.clone().add(clinic.position).project(camera)
        return { key, x: (v.x * 0.5 + 0.5) * w, y: (-v.y * 0.5 + 0.5) * h }
      })
    },
    setDark() { renderer.render(scene, camera) },
    dispose() {
      controls.dispose()
      disposables.forEach((d) => d.dispose())
      scene.traverse((o) => { if (o instanceof Mesh) { o.geometry.dispose(); const m = o.material as Material; m.dispose() } })
      renderer.dispose()
    },
    onChange(fn) { changeFn = fn },
  }
  return handle
}
