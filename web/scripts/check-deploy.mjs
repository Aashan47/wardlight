// Deploy check, headless only (never opens a window): the main screens and the health-facility pages load with
// no console errors and no horizontal overflow at 390 and 1440 px, the API answers with the expected data version,
// and the brief 13 agent recordings are listed.
//   BASE=http://127.0.0.1:8766 node scripts/check-deploy.mjs
//   BASE=https://wardlight.aashanjaved.com node scripts/check-deploy.mjs
// Exit code 1 on any failure.
import { chromium } from 'playwright-core'

const BASE = (process.env.BASE ?? 'http://127.0.0.1:8766').replace(/\/$/, '')
const VERSION = process.env.DATA_VERSION ?? '8606a23e82d2'
const fails = []
const j = async (p) => { const r = await fetch(BASE + p); if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`); return r.json() }

const health = await j('/api/health')
if (health.data_version !== VERSION || health.fixture) fails.push(`health: data_version ${health.data_version}, fixture ${health.fixture}`)
const recs = (await j('/api/agent/recordings')).recordings.map((r) => r.name)
const want = ['planner13_live_maiduguri', 'planner13_maiduguri_two_months', 'verifier13_borehole_sms', 'watcher13_line_cut_2024']
for (const w of want) if (!recs.includes(w)) fails.push(`recordings: ${w} missing`)
console.log('health', health.data_version, 'recordings', recs.length, recs.filter((r) => r.includes('13')).length, 'brief 13')

const sites = await j('/api/city/maiduguri/sites')
const site = sites.features.find((f) => f.properties.rank === 1)?.properties
const fid = sites.features.find((f) => f.properties.sector === 'health' && f.properties.facility_id && f.properties.rank)?.properties.facility_id
const paths = ['/', '/plan', `/site/${site.id}?city=maiduguri`, '/method', '/about', '/facilities', `/facility/${fid}`, `/facility/${fid}/sheet`]

const b = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
for (const width of [390, 1440]) {
  for (const path of paths) {
    const ctx = await b.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' })
    const p = await ctx.newPage()
    const errs = []
    p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
    p.on('pageerror', (e) => errs.push(String(e)))
    p.on('response', (r) => { if (r.url().includes('/api/') && r.status() >= 400) errs.push(`HTTP ${r.status()} ${r.url()}`) })
    await p.goto(BASE + path, { waitUntil: 'load', timeout: 60000 })
    await p.waitForSelector('main h1', { timeout: 30000 }).catch(() => errs.push('no h1'))
    await p.waitForTimeout(4000)
    const over = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    const ok = errs.length === 0 && over <= 0
    if (!ok) fails.push(`${width} ${path}: ${errs.length} errors ${errs.slice(0, 2).join(' | ').slice(0, 200)}; overflow ${over}`)
    console.log(width, path, 'errors', errs.length, 'overflow', over, ok ? 'ok' : 'FAIL')
    await ctx.close()
  }
}
await b.close()
if (fails.length) { console.log('\nFAILED\n' + fails.join('\n')); process.exit(1) }
console.log('\nall checks passed')
