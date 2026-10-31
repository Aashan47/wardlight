// Headless screenshots (never a visible window). Usage:
//   node scripts/shots.mjs still            -> public/stills/clinic-night.png from the live 3D scene
//   node scripts/shots.mjs all              -> screenshots/ matrix: 390 and 1440, light and dark, WebGL on and off
// Needs `npm run build && npx vite preview --port 4173` running.
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BASE = process.env.BASE ?? 'http://localhost:4173'
const out = (p) => fileURLToPath(new URL(`../${p}`, import.meta.url))
const GL_ON = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
const GL_OFF = ['--disable-3d-apis', '--disable-webgl']

async function setRange(page, sel, value) {
  await page.$eval(sel, (el, v) => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    set.call(el, String(v)); el.dispatchEvent(new Event('input', { bubbles: true }))
  }, value)
}

async function still() {
  const b = await chromium.launch({ headless: true, args: GL_ON })
  const ctx = await b.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: 'dark', deviceScaleFactor: 1 })
  const p = await ctx.newPage()
  await p.goto(`${BASE}/facility/WL-0001`, { waitUntil: 'networkidle' })
  await p.waitForSelector('.stage canvas')
  await setRange(p, '#sl-Battery', 1)
  await p.waitForTimeout(600)
  await setRange(p, '#scrub', 4.5)
  await p.waitForTimeout(900)
  const stage = await p.$('.stage')
  await p.$$eval('.stage .hud, .stage .lbl', (els) => els.forEach((el) => { el.style.visibility = 'hidden' }))
  await stage.screenshot({ path: out('public/stills/clinic-night.png') })
  await b.close()
  console.log('still written')
}

const ROUTES = [
  ['overview', '/facilities'],
  ['facility', '/facility/WL-0001'],
  ['facility-refused', null],
  ['plan', '/plan'],
  ['feeder', '/feeder/bedc-govt-house'],
  ['method', '/method'],
  ['about', '/about'],
  ['sheet', '/facility/WL-0001/sheet'],
]

async function matrix() {
  mkdirSync(out('screenshots'), { recursive: true })
  const facilities = await (await fetch(`${BASE}/fixtures/facilities.json`)).json()
  const refused = facilities.find((f) => f.tier === 'd_refused').id
  const report = []
  for (const gl of [true, false]) {
    for (const width of [390, 1440]) for (const scheme of ['light', 'dark']) {
      const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : null // e.g. ONLY=plan,feeder
      const routes = (gl ? ROUTES : ROUTES.filter(([n]) => ['overview', 'facility', 'plan'].includes(n))).filter(([n]) => !ONLY || ONLY.includes(n))
      for (const [name, path0] of routes) {
        const b = await chromium.launch({ headless: true, args: gl ? GL_ON : GL_OFF })
        const ctx = await b.newContext({ viewport: { width, height: width < 600 ? 844 : 1000 }, colorScheme: scheme, deviceScaleFactor: 1, serviceWorkers: 'block' })
        const path = path0 ?? `/facility/${refused}`
        await ctx.addInitScript((s) => { try { localStorage.setItem('wl-theme', s) } catch { /* blocked */ } }, scheme)
        const p = await ctx.newPage()
        const errors = []
        p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
        p.on('pageerror', (e) => errors.push(String(e)))
        p.on('requestfailed', (r) => { if (!r.url().includes('tiles.openfreemap.org')) errors.push(`requestfailed ${r.url()}`) })
        await p.goto(BASE + path, { waitUntil: 'load', timeout: 60000 }); await p.waitForSelector('main h1, main .sheet', { timeout: 20000 })
        if (name === 'facility') {
          if (gl) await p.waitForSelector('.stage canvas', { timeout: 20000 })
          await setRange(p, '#sl-Battery', 1)
          await p.waitForTimeout(500)
          await setRange(p, '#scrub', 7.3)
        }
        if (name === 'plan') await setRange(p, '#budget', 0.4)
        if (name === 'overview' || name === 'plan') await p.waitForTimeout(gl ? 3500 : 500)
        else await p.waitForTimeout(800)
        const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
        const file = `screenshots/${name}-${width}-${scheme}-${gl ? 'webgl' : 'nowebgl'}.png`
        const h = await p.evaluate(() => document.documentElement.scrollHeight)
        process.stdout.write(`${file} h=${h}\n`)
        try { await p.screenshot({ path: out(file), fullPage: true }) }
        catch (e) { errors.push(`fullPage capture failed (${String(e).slice(0, 80)}); viewport only`); await p.screenshot({ path: out(file) }) }
        report.push({ file, errors, overflow })
        await b.close()
      }
    }
  }
  for (const r of report) console.log(`${r.overflow > 0 ? 'OVERFLOW ' + r.overflow : 'ok'}\t${r.errors.length} err\t${r.file}${r.errors.length ? '\n   ' + r.errors.join('\n   ') : ''}`)
}

// Agent runs: a mid-run frame and an end frame of each agent panel, plus one reduced-motion end frame.
const AGENTS = [
  ['planner', '/plan', 'Ask Wardlight', '.agent-grid', 4600],
  ['verifier', '/facility/WL-0001', 'Verify this clinic by SMS', 'section[aria-label="Verify this clinic by SMS"]', 5300],
  ['watcher', '/method', 'Regulator watch', 'section[aria-label="Regulator watch"]', 5200],
]
async function agents() {
  mkdirSync(out('screenshots'), { recursive: true })
  const report = []
  const cases = []
  for (const a of AGENTS) for (const width of [390, 1440]) for (const scheme of ['light', 'dark']) cases.push([a, width, scheme, 'no-preference'])
  cases.push([AGENTS[0], 1440, 'light', 'reduce'])
  for (const [[kind, path, title, sel, mid], width, scheme, motion] of cases) {
    const b = await chromium.launch({ headless: true, args: GL_ON })
    const ctx = await b.newContext({ viewport: { width, height: width < 600 ? 844 : 1000 }, colorScheme: scheme, reducedMotion: motion, deviceScaleFactor: 1, serviceWorkers: 'block' })
    const p = await ctx.newPage()
    const errors = []
    p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    p.on('pageerror', (e) => errors.push(String(e)))
    await p.goto(BASE + path, { waitUntil: 'load' }); await p.waitForSelector('main h1')
    if (kind === 'planner') await p.waitForTimeout(2500)
    const panel = p.locator(`section[aria-label="${title}"]`)
    await panel.scrollIntoViewIfNeeded()
    await panel.getByRole('button', { name: /Replay the session|Run/ }).first().click()
    const tag = `${kind}-${width}-${scheme}${motion === 'reduce' ? '-reduced' : ''}`
    if (motion !== 'reduce') {
      await p.waitForTimeout(mid)
      await p.locator(sel).first().screenshot({ path: out(`screenshots/agent-${tag}-mid.png`) })
    }
    await panel.locator('footer.agent-foot').waitFor({ timeout: 20000 })
    await p.waitForTimeout(2600)
    await p.locator(sel).first().screenshot({ path: out(`screenshots/agent-${tag}-end.png`) })
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    report.push({ tag, errors, overflow })
    await b.close()
  }
  for (const r of report) console.log(`${r.overflow > 0 ? 'OVERFLOW ' + r.overflow : 'ok'}\t${r.errors.length} err\t${r.tag}${r.errors.length ? '\n   ' + r.errors.join('\n   ') : ''}`)
}

if (process.argv[2] === 'still') await still()
else if (process.argv[2] === 'agents') await agents()
else await matrix()
