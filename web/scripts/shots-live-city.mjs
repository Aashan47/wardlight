// Live integration check for the brief 13 screens, headless. Needs the API and a preview that proxies /api to it:
//   (build/wardlight) .venv/bin/uvicorn --factory api.main:create_app --host 127.0.0.1 --port 8422
//   (web) API_PROXY=http://127.0.0.1:8422 npx vite preview --port 4174
//   BASE=http://localhost:4174 node scripts/shots-live-city.mjs
// Screenshots go to screenshots/live-*.png.
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BASE = process.env.BASE ?? 'http://localhost:4174'
const out = (p) => fileURLToPath(new URL(`../screenshots/${p}`, import.meta.url))
const GL_ON = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
mkdirSync(out(''), { recursive: true })
const report = []
const fails = []
const check = (name, ok, detail = '') => { if (!ok) fails.push(`${name}: ${detail}`) }
const j = async (p) => (await fetch(BASE + p)).json()

async function open(path, { width = 1440, height = 1000, scheme = 'dark' } = {}) {
  const b = await chromium.launch({ headless: true, args: GL_ON })
  const ctx = await b.newContext({ viewport: { width, height }, colorScheme: scheme, deviceScaleFactor: 1, serviceWorkers: 'block' })
  await ctx.addInitScript((s) => { try { localStorage.setItem('wl-theme', s) } catch { /* blocked */ } }, scheme)
  const p = await ctx.newPage()
  const errors = []
  const fixtureHits = []
  p.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text().slice(0, 200)}`) })
  p.on('pageerror', (e) => errors.push(`pageerror: ${String(e).slice(0, 300)}`))
  p.on('response', (r) => { const u = r.url(); if (u.includes('/fixtures/brief13/')) fixtureHits.push(u); if (r.status() >= 400 && !u.includes('openfreemap')) errors.push(`HTTP ${r.status()} ${u}`) })
  await p.goto(BASE + path, { waitUntil: 'load', timeout: 60000 })
  await p.waitForSelector('main h1', { timeout: 30000 })
  return { p, errors, fixtureHits, close: () => b.close() }
}
const overflow = (p) => p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
const emDash = (p) => p.evaluate(() => (document.body.innerText.match(/—/g) ?? []).length)
async function shoot(p, path, full = false) {
  try { await p.screenshot({ path, fullPage: full }) }
  catch { const h = Math.min(9000, await p.evaluate(() => document.documentElement.scrollHeight)); await p.setViewportSize({ width: 1440, height: h }); await p.waitForTimeout(1200); await p.screenshot({ path }) }
}
async function done(tag, o) { report.push({ tag, errors: [...o.errors], overflow: await overflow(o.p), em: await emDash(o.p), fixtures: o.fixtureHits.length }); await o.close() }

// 1. scoreboard, every city at 14, 40 and 60 days: the hero must carry the API's own numbers
for (const city of ['maiduguri', 'damaturu', 'yola']) for (const days of [14, 40, 60]) {
  const path = `${city === 'maiduguri' ? '/' : `/city/${city}`}${days === 60 ? '' : `?days=${days}`}`
  const o = await open(path)
  await o.p.waitForSelector('.tile-num', { timeout: 30000 })
  await o.p.waitForTimeout(4000)
  const api = await j(`/api/city/${city}/metrics?days=${days}`)
  const hero = (await o.p.textContent('#hero-h'))?.replace(/\s+/g, ' ').trim()
  check(`hero ${city} ${days}`, hero === api.headline, `UI "${hero}" vs API "${api.headline}"`)
  check(`live source ${city} ${days}`, (await o.p.locator('.fxb, .mockb').count()) === 0, 'a recorded or mock badge is showing')
  const full = city === 'maiduguri' && days === 60
  await shoot(o.p, out(`live-city-${city}-${days}-1440-dark.png`), full)
  await done(`city ${city} ${days}`, o)
}
{
  const o = await open('/', { scheme: 'light' }); await o.p.waitForSelector('.tile-num'); await o.p.waitForTimeout(4000)
  await shoot(o.p, out('live-city-maiduguri-60-1440-light.png'), true); await done('city light', o)
}
{
  const o = await open('/', { width: 390, height: 844 }); await o.p.waitForSelector('.tile-num'); await o.p.waitForTimeout(4000)
  await shoot(o.p, out('live-city-maiduguri-60-390-dark.png'), true); await done('city 390', o)
}

// 2. the map, played; then the cost view and a siting card
{
  const o = await open('/', { width: 1920, height: 1080 })
  await o.p.waitForSelector('.tile-num'); await o.p.waitForTimeout(4500)
  await o.p.evaluate(() => document.getElementById('sec-map').scrollIntoView({ block: 'start' }))
  await o.p.waitForTimeout(800)
  await o.p.locator('#sec-map button.play').click()
  const t0 = Date.now()
  for (const [t, name] of [[2300, 'cut'], [5200, 'dark'], [11000, 'plan']]) {
    await o.p.waitForTimeout(Math.max(0, t - (Date.now() - t0)))
    await o.p.screenshot({ path: out(`live-play-${name}-1920.png`) })
  }
  await o.p.evaluate(() => document.getElementById('sec-cost').scrollIntoView({ block: 'start' }))
  await o.p.waitForTimeout(600)
  await o.p.screenshot({ path: out('live-cost-1920.png') })
  await o.p.evaluate(() => window.scrollBy(0, 900)); await o.p.waitForTimeout(400)
  await o.p.screenshot({ path: out('live-cost-arms-1920.png') })
  await o.p.locator('.t-sustainability .tile-open').click({ trial: false }).catch(() => {})
  await o.p.waitForSelector('dialog.drawer[open]', { timeout: 10000 }).catch(() => {})
  await o.p.waitForTimeout(500)
  const links = await o.p.locator('dialog.drawer .src-list a').count()
  check('drawer source links', links > 0, `${links} links`)
  await o.p.evaluate(() => document.querySelector('dialog.drawer .src-list')?.scrollIntoView({ block: 'center' }))
  await o.p.waitForTimeout(300)
  await o.p.screenshot({ path: out('live-evidence-sources-1920.png') })
  await done('play + cost + drawer', o)
}

// 3. the outage at one site: a clinic (3D), a solar borehole, a motorized borehole, a market cold room
for (const [kind, label] of [['clinic', 'A clinic'], ['solar-borehole', 'A solar borehole'], ['motorized-borehole', 'A motorized borehole'], ['cold-room', 'A market cold room']]) {
  const o = await open('/', { width: 1440, height: 1100 })
  await o.p.waitForSelector('.tile-num'); await o.p.waitForTimeout(2500)
  await o.p.evaluate(() => document.getElementById('sec-night').scrollIntoView({ block: 'start' }))
  await o.p.locator('#sec-night button.chip', { hasText: label }).click()
  const ok = await o.p.waitForSelector('#sec-night .stage canvas, #sec-night .strip svg', { timeout: 40000 }).then(() => true, () => false)
  check(`outage ${kind}`, ok, await o.p.textContent('#sec-night').then((t) => t?.slice(0, 200)))
  await o.p.waitForTimeout(kind === 'clinic' ? 2500 : 800)
  if (ok) { await o.p.locator('#sec-night button:has-text("Run the night")').click(); await o.p.waitForTimeout(5000) }
  await o.p.evaluate(() => document.getElementById('sec-night').scrollIntoView({ block: 'start' }))
  await o.p.waitForTimeout(300)
  await o.p.screenshot({ path: out(`live-outage-${kind}-1440.png`) })
  await done(`outage ${kind}`, o)
}

// 4. a siting card page, and the agent pages still load
{
  const sites = await j('/api/city/maiduguri/sites')
  const top = sites.features.map((f) => f.properties).filter((x) => x.rank != null).sort((a, b) => a.rank - b.rank)[0]
  const o = await open(`/site/${encodeURIComponent(top.id)}?city=maiduguri&days=60`)
  await o.p.waitForSelector('.siting', { timeout: 30000 }); await o.p.waitForTimeout(3000)
  await shoot(o.p, out('live-site-1440-dark.png'), true)
  await done('site', o)
  const fid = sites.features.map((f) => f.properties).find((x) => x.facility_id)?.facility_id
  for (const [tag, path] of [['plan', '/plan'], ['method', '/method'], ['facilities', '/facilities'], ['facility', `/facility/${fid}`]]) {
    const a = await open(path)
    await a.p.waitForTimeout(3000)
    await a.p.screenshot({ path: out(`live-page-${tag}-1440-dark.png`) })
    await done(`page ${tag}`, a)
  }
}

let bad = 0
for (const r of report) {
  const flag = r.errors.length || r.overflow > 0 || r.em > 0
  if (flag) bad++
  console.log(`${flag ? 'FLAG' : 'ok  '}\t${r.errors.length} err\toverflow ${r.overflow}\temdash ${r.em}\tfixture reads ${r.fixtures}\t${r.tag}${r.errors.length ? '\n   ' + r.errors.slice(0, 6).join('\n   ') : ''}`)
}
console.log(`\n${report.length} pages, ${bad} flagged; ${fails.length} functional failures${fails.length ? '\n  ' + fails.join('\n  ') : ''}`)
