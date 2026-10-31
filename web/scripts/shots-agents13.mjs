// Headless screenshots of the brief 13 agent screens and the Funder plan (never a visible window).
//   BASE=http://127.0.0.1:8765 node scripts/shots-agents13.mjs      (a running API that serves web/dist)
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8765'
const out = (p) => fileURLToPath(new URL(`../screenshots/${p}`, import.meta.url))
mkdirSync(out(''), { recursive: true })
const report = []

// ONLY=tag1,tag2 re-takes just those; a shot that fails is reported and the run goes on
const ONLY = process.env.ONLY ? new Set(process.env.ONLY.split(',')) : null
async function shot(tag, path, opts = {}) {
  if (ONLY && !ONLY.has(tag)) return
  try { await take(tag, path, opts) } catch (e) { report.push({ tag, failed: String(e).split('\n')[0] }) }
}
async function take(tag, path, { width = 1440, height = 1000, scheme = 'dark', act } = {}) {
  const b = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
  const ctx = await b.newContext({ viewport: { width, height }, colorScheme: scheme, deviceScaleFactor: 1, serviceWorkers: 'block' })
  await ctx.addInitScript((s) => { try { localStorage.setItem('wl-theme', s) } catch { /* blocked */ } }, scheme)
  const p = await ctx.newPage()
  const errors = []
  p.on('pageerror', (e) => errors.push(String(e)))
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()) })
  await p.goto(BASE + path, { waitUntil: 'load', timeout: 60000 })
  await p.waitForSelector('main h1', { timeout: 30000 })
  await p.waitForTimeout(2500)
  if (act) await act(p)
  try { await p.screenshot({ path: out(`${tag}.png`), fullPage: true }) }
  catch {
    // tall pages with a WebGL canvas can fail as one capture: grow the viewport instead
    const h = Math.min(9000, await p.evaluate(() => document.documentElement.scrollHeight))
    await p.setViewportSize({ width, height: h }); await p.waitForTimeout(1200)
    await p.screenshot({ path: out(`${tag}.png`) })
  }
  const text = await p.evaluate(() => document.body.innerText)
  report.push({ tag, errors: errors.length, errorText: errors.slice(0, 2), emdash: (text.match(/—/g) ?? []).length, kano: /Kano|vaccine doses|fridge stay cold/.test(text),
    overflow: await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth) })
  await b.close()
}
// a hung run must not leave a browser open: take() closes in the normal path; a throw leaves it to process exit
const replay = (chip) => async (p) => {
  // the scripted Maiduguri chip and the live one share their opening words
  if (chip) await p.locator('button.chip.pick', { hasText: chip, ...(chip === '(live model)' ? {} : { hasNotText: '(live model)' }) }).first().click()
  await p.getByRole('button', { name: /Replay this session/ }).click()
  await p.waitForSelector('.agent .agent-foot', { timeout: 60000 }); await p.waitForTimeout(3000)
}

await shot('b13-plan-1440-dark-start', '/plan')
await shot('b13-agent-planner-maiduguri-1440-dark-end', '/plan', { act: replay('Maiduguri: the line') })
await shot('b13-agent-planner-maiduguri-1440-light-end', '/plan', { scheme: 'light', act: replay('Maiduguri: the line') })
await shot('b13-agent-planner-live-1440-dark-end', '/plan', { act: replay('(live model)') })
await shot('b13-agent-planner-grounding-1440-dark-end', '/plan', { act: replay('grounding check') })
await shot('b13-agent-planner-damaturu-1440-dark-end', '/plan', { act: replay('Damaturu') })
await shot('b13-agent-planner-refusal-attack-1440-dark-end', '/plan', { act: replay('forecast attacks') })
await shot('b13-agent-planner-maiduguri-390-dark-end', '/plan', { width: 390, height: 844, act: replay('Maiduguri: the line') })
await shot('b13-agent-watcher-1440-dark-end', '/plan', { act: async (p) => {
  await p.getByRole('button', { name: /Replay the 2024 line cut/ }).click()
  await p.waitForFunction(() => document.querySelectorAll('.agent .agent-foot').length > 0, null, { timeout: 60000 }); await p.waitForTimeout(3000)
  await p.locator('#watch-h').scrollIntoViewIfNeeded()
} })
await shot('b13-agent-verifier-1440-dark-end', '/site/W-BH-589?city=maiduguri', { act: async (p) => {
  await p.getByRole('button', { name: /Replay the recorded session/ }).click()
  await p.waitForSelector('.agent .agent-foot', { timeout: 60000 }); await p.waitForTimeout(2500)
} })
await shot('b13-plan-brief-1440-light', '/plan/brief?city=maiduguri&budget=2000000000&days=60&sectors=health,water,cold', { scheme: 'light' })
await shot('b13-plan-damaturu-390-light', '/plan', { width: 390, height: 844, scheme: 'light', act: async (p) => { await p.getByRole('radio', { name: /Damaturu/ }).first().click(); await p.waitForTimeout(2000) } })
await shot('b13-about-1440-dark', '/about')
await shot('b13-method-1440-dark', '/method')
console.log(JSON.stringify(report, null, 1))
