# Wardlight web

React, TypeScript and Vite. Routes: `/` (brief 13 city scoreboard, Maiduguri), `/city/:city?days=14|40|60`
(`maiduguri`, `damaturu`, `yola`), `/site/:id` (siting card and the 3D outage night), `/facilities` (the health layer
of the city plan, and national registry search), `/facility/:id` (plus `/facility/:id/sheet`, printable), `/plan`,
`/feeder/:id`, `/method`, `/about`.

```sh
npm install
npm run build                      # live: the typed client calls the API at /api (same origin)
VITE_API_BASE=https://host/api npm run build   # live, API elsewhere
VITE_FIXTURES=1 npm run build      # fallback: sample fixtures from ../data/fixtures/web, no API
npm run dev                        # dev server; /api is proxied to API_PROXY (default http://127.0.0.1:8000)
```

- `src/api/client.ts` is the only place that talks to data; shapes in `src/api/types.ts`.
- Brief 13: `src/api/brief13-client.ts` reads `/api/city/{city}/metrics?days=`, `/api/city/{city}/sites`, `/api/corridor`
  and `/api/sites/{id}/siting`; when the API does not answer it reads the engine's recorded outputs in
  `../data/fixtures/brief13/` (served at `/fixtures/brief13/`, shipped in every build, marked "Recorded engine output").
  `brief13-normalize.ts` maps the engine's field names onto the contract types in `brief13.ts`. `brief13-mock.ts` is a
  typed MOCK used only by `npm run dev` or `VITE_BRIEF13_MOCK=1`, and every screen that shows it says "Mock data".
  The 3D outage night calls `/api/facilities/{id}/outage_trace?days=` and needs the live engine.
- `node scripts/shots-city.mjs` takes headless screenshots of the city screens, the evidence drawers and the played
  outage against `npx vite preview --port 4173`.
- Funder plan (`/plan`, brief 13): city, budget in naira, outage length and sectors -> the sites the budget funds, in the
  city's plan order (`src/api/cityplan.ts`, the same rule as `agents/city13.py` and `GET /api/city/{city}/plan`;
  `BASE=http://127.0.0.1:8765 node scripts/check-plan-parity.mjs` checks the two agree). `/plan/brief?city=&budget=&days=&sectors=`
  is the printable investment brief; CSV from the page or `GET /api/city/{city}/plan.csv`. The brief 1 facility brief
  moved to `/facilities/brief`.
- Brief 13 agents: the planner and the line watcher on `/plan`, the SMS site verifier on `/site/:id`
  (`src/agent/SiteVerifyPanel.tsx`, `src/agent/LineWatchPanel.tsx`). `BASE=... node scripts/shots-agents13.mjs` takes
  their headless screenshots (`ONLY=tag1,tag2` re-takes some).
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
- `BASE=http://127.0.0.1:8766 node scripts/check-deploy.mjs`: the deploy check used in `../deploy/SUNDAY-RUNBOOK.md` (main
  screens and health-facility pages at 390 and 1440 px, console errors, overflow, data version, brief 13 recordings).
  `VITE_FIXTURES=1` health-facility records are synthetic samples (Edo State), labelled on screen;
  the brief 13 screens use the recorded engine output in `../data/fixtures/brief13/` in every mode.
