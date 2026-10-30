// Renders the PWA icons from the ring logo with headless Chromium (no visible window).
import { chromium } from 'playwright-core'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const svg = readFileSync(new URL('../public/favicon.svg', import.meta.url), 'utf8')
const b = await chromium.launch({ headless: true })
const p = await b.newPage()
for (const [name, size, pad] of [['icon-192', 192, 0], ['icon-512', 512, 0], ['icon-maskable-512', 512, 0.12]]) {
  await p.setViewportSize({ width: size, height: size })
  const inner = size * (1 - 2 * pad)
  await p.setContent(`<body style="margin:0;background:#0E1420;display:grid;place-items:center;width:${size}px;height:${size}px">${svg.replace('<svg ', `<svg width="${inner}" height="${inner}" `)}</body>`)
  await p.screenshot({ path: fileURLToPath(new URL(`../public/icons/${name}.png`, import.meta.url)) })
}
await b.close()
console.log('icons written')
