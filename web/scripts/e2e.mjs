// Headless end-to-end check against a running API that serves web/dist (deploy/run.sh). Never opens a window.
//   BASE=http://127.0.0.1:8765 node scripts/e2e.mjs
// Agents run in recorded mode only (no model calls). Screenshots go to screenshots/live-*.png.
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8765'
const out = (p) => fileURLToPath(new URL(`../${p}`, import.meta.url))
const GL_ON = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
const GL_OFF = ['--disable-3d-apis', '--disable-webgl']
mkdirSync(out('screenshots'), { recursive: true })
const j = async (p) => (await fetch(BASE + p)).json()

const refused = (await j('/api/facilities?tier=d_refused&limit=1'))[0].id
const named = (await j('/api/facilities?q=Bichi%20General%20Hospital&limit=5')).find((f) => /^bichi general hospital$/i.test(f.name))
const bichi = await j(`/api/facilities/${named.id}`)
const auchi = (await j('/api/facilities?q=auchi%20general&limit=1'))[0]
const rec = await j(`/api/facilities/${auchi.id}`)
const verifierId = (await j('/api/agent/recordings')).recordings.find((r) => r.agent === 'verifier').facility_id

const ROUTES = [
  ['city', '/'], ['city-damaturu', '/city/damaturu?days=40'], ['overview', '/facilities'], ['facility', `/facility/${auchi.id}`], ['facility-named', `/facility/${named.id}`], ['facility-refused', `/facility/${refused}`],
  ['sheet', `/facility/${auchi.id}/sheet`], ['plan', '/plan'], ['brief', '/plan/brief?city=maiduguri&budget=2000000000&days=60&sectors=health,water,cold'], ['feeder', `/feeder/${bichi.match.feeder_id}`], ['method', '/method'], ['about', '/about'],
]
const report = []
const fails = []

async function page(b, width, scheme, motion = 'no-preference') {
  const ctx = await b.newContext({ viewport: { width, height: width < 600 ? 844 : 1000 }, colorScheme: scheme, reducedMotion: motion, deviceScaleFactor: 1, serviceWorkers: 'block' })
  await ctx.addInitScript((s) => { try { localStorage.setItem('wl-theme', s) } catch { /* blocked */ } }, scheme) // the app is dark-first
  const p = await ctx.newPage()
  const errors = []
  p.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`) })
  p.on('pageerror', (e) => errors.push(`pageerror: ${e}`))
  p.on('requestfailed', (r) => { if (!r.url().includes('openfreemap') && !/net::ERR_ABORTED/.test(r.failure()?.errorText ?? '')) errors.push(`requestfailed ${r.url()} ${r.failure()?.errorText}`) })
  p.on('response', (r) => { if (r.url().includes('/api/') && r.status() >= 400) errors.push(`HTTP ${r.status()} ${r.url()}`) })
  return { p, errors, close: () => ctx.close() }
}
const check = (name, ok, detail = '') => { if (!ok) fails.push(`${name}: ${detail}`) }
const shoot = async (p, sel, path) => {
  try { await p.locator(sel).first().screenshot({ path, timeout: 15000 }) }
  catch { await p.locator(sel).first().scrollIntoViewIfNeeded().catch(() => {}); await p.screenshot({ path, fullPage: false }) }
}

// 1. every route, 390 and 1440, light and dark, WebGL on; plus WebGL off for the 3D and map pages
for (const gl of [true, false]) {
  for (const width of [390, 1440]) for (const scheme of ['light', 'dark']) {
    for (const [name, path] of ROUTES) {
      if (!gl && !['overview', 'facility', 'plan'].includes(name)) continue
      if (!gl && scheme === 'dark') continue
      const b = await chromium.launch({ headless: true, args: gl ? GL_ON : GL_OFF })
      const { p, errors, close } = await page(b, width, scheme)
      await p.goto(BASE + path, { waitUntil: 'load', timeout: 60000 })
      await p.waitForSelector('main h1, main .sheet h1', { timeout: 30000 })
      await p.waitForTimeout(name === 'overview' || name === 'plan' ? 3500 : 1500)
      const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      const sampleMarks = await p.locator('.sample').count()
      const tag = `live-${name}-${width}-${scheme}-${gl ? 'webgl' : 'nowebgl'}`
      try { await p.screenshot({ path: out(`screenshots/${tag}.png`), fullPage: true }) } catch { await p.screenshot({ path: out(`screenshots/${tag}.png`) }) }
      report.push({ tag, errors: [...errors], overflow, sampleMarks })
      await close(); await b.close()
    }
  }
}

// 2. interactions on the live API: what-if, SMS route, the three recorded agents (mid-run and end frames)
{
  const b = await chromium.launch({ headless: true, args: GL_ON })
  const { p, errors, close } = await page(b, 1440, 'light')
  await p.goto(`${BASE}/facility/${auchi.id}`, { waitUntil: 'load' }); await p.waitForSelector('main h1')
  const sim = p.waitForResponse((r) => r.url().includes('/simulate'), { timeout: 30000 })
  await p.$eval('#sl-Battery', (el) => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, '12'); el.dispatchEvent(new Event('input', { bubbles: true })) })
  const simRes = await sim
  check('what-if', simRes.status() === 200, `simulate ${simRes.status()}`)
  await p.fill('input[aria-describedby="sms-help"]', String(auchi.code))
  await p.click('button.send')
  await p.waitForFunction(() => /Auchi/.test(document.querySelector('.phone .screen')?.textContent ?? ''), null, { timeout: 15000 }).catch(() => {})
  const smsText = await p.textContent('.phone .screen')
  check('sms 5-digit code', /Auchi/.test(smsText ?? ''), smsText)
  // health facilities (brief 13 health layer): plan-order list, the NERC row of the first-ranked named facility, no dose wording
  await p.goto(`${BASE}/facilities`, { waitUntil: 'load' }); await p.waitForSelector('main h1')
  await p.waitForSelector('img.crop', { timeout: 20000 }).catch(() => {})
  const crop = await p.$eval('img.crop', (i) => ({ ok: i.complete && i.naturalWidth > 0, src: i.getAttribute('src') })).catch(() => ({ ok: false, src: null }))
  check('hero crop image', crop.ok, JSON.stringify(crop))
  check('hero NERC row', ((await p.textContent('.nerc').catch(() => '')) ?? '').length > 10, 'hero row text')
  const ovText = await p.textContent('main') ?? ''
  check('overview is the Maiduguri health layer', /Maiduguri: health facilities in plan order/.test(ovText) && /critical service-hours/i.test(ovText), 'heading')
  check('overview has no dose wording', !/\bdoses?\b/i.test(ovText), 'dose wording')
  // facility: draw label
  await p.goto(`${BASE}/facility/${named.id}`, { waitUntil: 'load' }); await p.waitForSelector('main h1')
  check('draw label', /Scenario:.*Draw: lane/s.test(await p.textContent('.draw-label').catch(() => '') ?? ''), 'missing')
  // feeder: served summary with the DisCo-wide wording
  await p.goto(`${BASE}/feeder/${bichi.match.feeder_id}`, { waitUntil: 'load' }); await p.waitForSelector('main h1')
  const feederText = await p.textContent('main')
  check('served summary', /Who depends on this feeder/.test(feederText ?? '') && /not this feeder/.test(feederText ?? ''), 'missing')
  // brief: JSON page and CSV
  await p.goto(`${BASE}/plan/brief?city=maiduguri&budget=2000000000&days=60&sectors=health,water,cold`, { waitUntil: 'load' }); await p.waitForSelector('.brief h1', { timeout: 30000 })
  check('brief rows', (await p.locator('.brief table tbody tr').count()) > 10, 'no rows')
  const briefText = await p.textContent('.brief') ?? ''
  check('brief is brief 13', /Maiduguri/.test(briefText) && /critical service-hours/i.test(briefText) && !/Kano|vaccine doses/.test(briefText), 'brief 1 wording')
  const csv = await fetch(`${BASE}/api/city/maiduguri/plan.csv?budget_ngn=2000000000&days=60`)
  const csvText = await csv.text()
  check('brief csv', csv.status === 200 && csvText.split('\n').length > 10, `status ${csv.status}`)
  report.push({ tag: 'interactions-facility', errors: [...errors], overflow: 0, sampleMarks: 0 })
  await close(); await b.close()
}

const AGENTS = [
  ['planner', '/plan', 'Ask Wardlight', /Replay this session/, '.agent-grid', 3200],
  ['verifier', '/site/W-BH-589?city=maiduguri', 'Verify this site by SMS', /Replay the recorded session/, 'section[aria-label="Verify this site by SMS"]', 2600],
  ['watcher', '/plan', 'Line watch', /Replay the 2024 line cut/, 'section[aria-label="Line watch"]', 2200],
]
for (const [kind, path, title, btn, sel, mid] of AGENTS) {
  for (const width of [390, 1440]) for (const scheme of ['light', 'dark']) {
    const b = await chromium.launch({ headless: true, args: GL_ON })
    const { p, errors, close } = await page(b, width, scheme)
    await p.goto(BASE + path, { waitUntil: 'load' }); await p.waitForSelector('main h1')
    const panel = p.locator(`section[aria-label="${title}"]`)
    await panel.getByRole('button', { name: btn }).waitFor({ timeout: 20000 })
    await p.waitForTimeout(kind === 'planner' ? 2500 : 300)
    await panel.scrollIntoViewIfNeeded()
    await panel.getByRole('button', { name: btn }).click()
    const tag = `live-agent-${kind}-${width}-${scheme}`
    await p.waitForTimeout(mid)
    await shoot(p, sel, out(`screenshots/${tag}-mid.png`))
    await panel.locator('footer.agent-foot').waitFor({ timeout: 60000 })
    await p.waitForTimeout(3000)
    await shoot(p, sel, out(`screenshots/${tag}-end.png`))
    const foot = await panel.locator('footer.agent-foot').textContent()
    check(`${kind} recorded label`, /recorded session/.test(foot ?? ''), foot)
    if (kind === 'planner') {
      check('planner set the city', /Maiduguri/.test(await p.textContent('#list-h') ?? ''), 'city did not follow the agent')
      check('planner answer is brief 13', /critical service-hours/.test(await panel.textContent() ?? ''), 'no brief 13 answer')
    }
    if (kind === 'verifier') check('verifier closes on the reported hours', /10 of 56/.test(await panel.textContent() ?? ''), (await panel.locator('ol.small').textContent().catch(() => '')) ?? '')
    report.push({ tag, errors: [...errors], overflow: await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), sampleMarks: 0 })
    await close(); await b.close()
  }
}

let bad = 0
for (const r of report) {
  const flag = r.errors.length || r.overflow > 0 || r.sampleMarks > 0
  if (flag) bad++
  console.log(`${flag ? 'FLAG' : 'ok  '}\t${r.errors.length} err\toverflow ${r.overflow}\tsample ${r.sampleMarks}\t${r.tag}${r.errors.length ? '\n   ' + r.errors.slice(0, 6).join('\n   ') : ''}`)
}
console.log(`\n${report.length} checks, ${bad} flagged; ${fails.length} functional failures${fails.length ? '\n  ' + fails.join('\n  ') : ''}`)
