import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

// Sample fixtures live outside the web app, in data/fixtures/web. Served at /fixtures/ in dev and
// copied into the build, so the app runs with no API until VITE_API_BASE is set.
const FIXTURES = resolve(__dirname, '../data/fixtures/web')
// Brief 13: the engine stream's recorded outputs (real engine runs, not synthetic), served at /fixtures/brief13/ and
// shipped with every build as the fallback when the live API does not answer.
const B13 = resolve(__dirname, '../data/fixtures/brief13')
const USE_FIXTURES = process.env.VITE_FIXTURES === '1'

function walk(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    return statSync(p).isDirectory() ? walk(p) : [p]
  })
}

function fixtures(): Plugin {
  return {
    name: 'wardlight-fixtures',
    configureServer(server) {
      server.middlewares.use('/fixtures/brief13', (req, res) => {
        const file = join(B13, decodeURIComponent((req.url ?? '').split('?')[0]))
        if (!file.startsWith(B13) || !existsSync(file) || statSync(file).isDirectory()) { res.statusCode = 404; res.end(); return }
        res.setHeader('Content-Type', 'application/json')
        res.end(readFileSync(file))
      })
      server.middlewares.use('/fixtures', (req, res, next) => {
        const file = join(FIXTURES, decodeURIComponent((req.url ?? '').split('?')[0]))
        if (!file.startsWith(FIXTURES) || !existsSync(file) || statSync(file).isDirectory()) return next()
        res.setHeader('Content-Type', 'application/json')
        res.end(readFileSync(file))
      })
    },
    generateBundle() {
      for (const file of walk(B13)) {
        this.emitFile({ type: 'asset', fileName: `fixtures/brief13/${relative(B13, file)}`, source: readFileSync(file) })
      }
      if (!USE_FIXTURES) return // live builds ship no sample files
      for (const file of walk(FIXTURES)) {
        this.emitFile({ type: 'asset', fileName: `fixtures/${relative(FIXTURES, file)}`, source: readFileSync(file) })
      }
    },
  }
}

export default defineConfig({
  plugins: [
    react(),
    fixtures(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'icons/*.png', 'stills/*.png'],
      manifest: {
        name: 'Wardlight',
        short_name: 'Wardlight',
        description: 'Critical power when the line is cut: which hospitals, water pumps and cold rooms keep running in Maiduguri, and what on-site solar keeps the rest running without diesel.',
        theme_color: '#0E1420',
        background_color: '#F7F6F2',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // app shell, fonts, stills and the small fixtures are precached; what-if grids and map tiles are cached on use
        globPatterns: USE_FIXTURES ? ['**/*.{js,css,html,svg,png,woff2}', 'fixtures/*.json', 'fixtures/facility/*.json', 'fixtures/feeder/*.json'] : ['**/*.{js,css,html,svg,png,woff2}'],
        maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/fixtures\//],
        runtimeCaching: [
          { urlPattern: ({ url }) => url.pathname.startsWith('/fixtures/simulate/'), handler: 'CacheFirst', options: { cacheName: 'wl-whatif', expiration: { maxEntries: 60 } } },
          // agent streams and POSTs are never cached; facility reads are, so saved sheets open offline
          { urlPattern: ({ url, request }) => request.method === 'GET' && url.pathname.startsWith('/api/') && !url.pathname.startsWith('/api/agent/'), handler: 'NetworkFirst', options: { cacheName: 'wl-api', networkTimeoutSeconds: 4, expiration: { maxEntries: 300 } } },
          { urlPattern: ({ url }) => url.hostname === 'tiles.openfreemap.org', handler: 'StaleWhileRevalidate', options: { cacheName: 'wl-tiles', expiration: { maxEntries: 400 } } },
        ],
      },
    }),
  ],
  build: { chunkSizeWarningLimit: 1200 },
  // dev: forward /api to a local API (deploy/run.sh); API_PROXY overrides the target
  server: { proxy: { '/api': { target: process.env.API_PROXY ?? 'http://127.0.0.1:8000', changeOrigin: true } } },
})
