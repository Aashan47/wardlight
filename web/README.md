# Wardlight web

React, TypeScript and Vite. Routes: `/`, `/facility/:id` (plus `/facility/:id/sheet`, printable), `/plan`,
`/feeder/:id`, `/method`, `/about`.

```sh
npm install
npm run build                      # live: the typed client calls the API at /api (same origin)
VITE_API_BASE=https://host/api npm run build   # live, API elsewhere
VITE_FIXTURES=1 npm run build      # fallback: sample fixtures from ../data/fixtures/web, no API
npm run dev                        # dev server; /api is proxied to API_PROXY (default http://127.0.0.1:8000)
```

- `src/api/client.ts` is the only place that talks to data; shapes in `src/api/types.ts`.
- Agents (`src/agent/`): a POST starts a run, then `GET /api/agent/runs/{id}/events` streams Server-Sent Events in
  agent F's schema (`agents/events.py`). Recorded sessions replay with `recorded: true`; the UI says "recorded session".
- `node scripts/make-fixtures.mjs` regenerates the SAMPLE fixtures used only with `VITE_FIXTURES=1` (a seeded toy model, labelled sample on
  every screen). Only the NERC row for feeder GOVT. HOUSE and the quoted sources are real.
- The 3D night clinic (`src/three/`) and the map (`src/map/BudgetMap.tsx`) are lazy chunks. No WebGL or
  reduced motion gets `public/stills/clinic-night.png`; the map falls back to an SVG column plot.
- `node scripts/shots.mjs all` takes headless screenshots into `screenshots/` (390 and 1440 px, light and
  dark, WebGL on and off) against `npx vite preview --port 4173`. `node scripts/shots.mjs still` re-renders
  the 3D still. `node scripts/make-icons.mjs` renders the PWA icons. `BASE=http://127.0.0.1:8765 node scripts/e2e.mjs`
  checks every route and the three recorded agents against a running API (`deploy/run.sh`). All headless.
