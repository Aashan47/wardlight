// Headless: city scoreboard at phone and desktop width, report console errors and horizontal overflow.
//   BASE=http://127.0.0.1:8765 node scripts/check-city-console.mjs
import { chromium } from 'playwright-core'
const BASE = process.env.BASE ?? 'http://127.0.0.1:8765'
const b = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
for (const width of [390, 1440]) {
  for (const path of ['/', '/?city=damaturu', '/plan']) {
    const p = await b.newPage({ viewport: { width, height: 900 } })
    const errs = []
    p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
    p.on('pageerror', (e) => errs.push(String(e)))
    await p.goto(BASE + path, { waitUntil: 'networkidle' })
    await p.waitForTimeout(2500)
    const over = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    console.log(width, path, 'errors:', errs.length, errs.slice(0, 2).join(' | ').slice(0, 200), 'overflow:', over)
    await p.close()
  }
}
await b.close()
