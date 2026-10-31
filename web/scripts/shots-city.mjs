// Headless screenshots of the brief 13 city screens (never a visible window).
//   npm run build && npx vite preview --port 4173 &   then   node scripts/shots-city.mjs
// BASE=http://127.0.0.1:8765 points it at a running API that serves web/dist instead.
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BASE = process.env.BASE ?? 'http://localhost:4173'
const out = (p) => fileURLToPath(new URL(`../screenshots/${p}`, import.meta.url))
const GL_ON = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
const GL_OFF = ['--disable-3d-apis', '--disable-webgl']
mkdirSync(out(''), { recursive: true })
const report = []

async function open(path, { width = 1440, height = 1000, scheme = 'dark', gl = true, motion = 'no-preference' } = {}) {
  const b = await chromium.launch({ headless: true, args: gl ? GL_ON : GL_OFF })
  const ctx = await b.newContext({ viewport: { width, height }, colorScheme: scheme, reducedMotion: motion, deviceScaleFactor: 1, serviceWorkers: 'block' })
  await ctx.addInitScript((s) => { try { localStorage.setItem('wl-theme', s) } catch { /* blocked */ } }, scheme)
  const p = await ctx.newPage()
  const errors = []
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()) })
  p.on('pageerror', (e) => errors.push(String(e)))
  p.on('response', (r) => { const u = r.url(); if (r.status() >= 400 && !u.includes('/api/') && !u.includes('openfreemap')) errors.push(`HTTP ${r.status()} ${u}`) })
  await p.goto(BASE + path, { waitUntil: 'load', timeout: 60000 })
  await p.waitForSelector('main h1', { timeout: 30000 })
  return { p, errors, close: () => b.close() }
}
const overflow = (p) => p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
const emDash = (p) => p.evaluate(() => (document.body.innerText.match(/—/g) ?? []).length)

async function page(tag, path, opts = {}, after) {
  const { p, errors, close } = await open(path, opts)
  await p.waitForSelector('.tile-num', { timeout: 30000 }).catch(() => {})
  await p.waitForTimeout(opts.gl === false ? 800 : 4500)
  if (after) await after(p)
  try { await p.screenshot({ path: out(`${tag}.png`), fullPage: opts.full !== false }) }
  catch {
    // tall pages with a WebGL canvas can fail as one capture: grow the viewport instead
    const h = Math.min(9000, await p.evaluate(() => document.documentElement.scrollHeight))
    await p.setViewportSize({ width: opts.width ?? 1440, height: h }); await p.waitForTimeout(1200)
    await p.screenshot({ path: out(`${tag}.png`) })
  }
  report.push({ tag, errors: [...errors], overflow: await overflow(p), em: await emDash(p) })
  await close()
}

// the scoreboard: 1080p video frame, 1440 and 390, both themes, no WebGL
await page('city-1920-dark-fold', '/', { width: 1920, height: 1080, full: false })
await page('city-1440-dark', '/')
await page('city-1440-light', '/', { scheme: 'light' })
await page('city-390-dark', '/', { width: 390, height: 844 })
await page('city-390-light', '/', { width: 390, height: 844, scheme: 'light' })
await page('city-1440-dark-nowebgl', '/', { gl: false })
await page('city-damaturu-40-1440-dark', '/city/damaturu?days=40')
await page('city-yola-14-1440-dark', '/city/yola?days=14')

// evidence drawers
for (const k of ['impact', 'sustainability', 'feasibility']) {
  await page(`evidence-${k}-1440-dark`, '/', { full: false }, async (p) => {
    await p.locator(`.t-${k} .tile-open`).click()
    await p.waitForSelector('dialog.drawer[open]')
    await p.waitForTimeout(500)
  })
}
await page('evidence-impact-390-dark', '/', { width: 390, height: 844, full: false }, async (p) => {
  await p.locator('.t-impact .tile-open').click(); await p.waitForSelector('dialog.drawer[open]'); await p.waitForTimeout(500)
})

// the outage, played: frames on the map section
{
  const { p, errors, close } = await open('/', { width: 1920, height: 1080 })
  await p.waitForSelector('.tile-num', { timeout: 30000 })
  await p.waitForTimeout(4500)
  const sec = p.locator('#sec-map')
  await sec.scrollIntoViewIfNeeded()
  await p.evaluate(() => document.getElementById('sec-map').scrollIntoView({ block: 'start' }))
  await p.waitForTimeout(800)
  await p.screenshot({ path: out('play-0-rest-1920.png') })
  await p.locator('#sec-map button.play').click()
  const t0 = Date.now()
  for (const [t, name] of [[1000, 'grid'], [2300, 'cut'], [5200, 'dark'], [8200, 'relight'], [11000, 'end']]) {
    await p.waitForTimeout(Math.max(0, t - (Date.now() - t0)))
    await p.screenshot({ path: out(`play-${t}-${name}-1920.png`) })
  }
  report.push({ tag: 'play', errors: [...errors], overflow: await overflow(p), em: await emDash(p) })
  await close()
}

// a site page
{
  const { p, close, errors } = await open('/', { full: false })
  await p.waitForSelector('.sites a.open', { timeout: 30000 })
  const href = await p.locator('.sites a.open').first().getAttribute('href')
  await close()
  report.push({ tag: 'site-href', errors, overflow: 0, em: 0, href })
  await page('site-1440-dark', href)
  await page('site-390-dark', href, { width: 390, height: 844 })
}

let bad = 0
for (const r of report) {
  const flag = r.errors.length || r.overflow > 0 || r.em > 0
  if (flag) bad++
  console.log(`${flag ? 'FLAG' : 'ok  '}\t${r.errors.length} err\toverflow ${r.overflow}\temdash ${r.em}\t${r.tag}${r.href ? ' ' + r.href : ''}${r.errors.length ? '\n   ' + r.errors.slice(0, 5).join('\n   ') : ''}`)
}
console.log(`\n${report.length} checks, ${bad} flagged`)
