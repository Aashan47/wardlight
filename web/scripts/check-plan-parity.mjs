// The Funder plan page computes the city plan in the browser (src/api/cityplan.ts); the planner agent and
// GET /api/city/{city}/plan compute it in Python (agents/city13.py). This checks they agree, against a running API.
//   BASE=http://127.0.0.1:8765 node scripts/check-plan-parity.mjs        (Node 23.6+: runs the .ts file directly)
import { planCity } from '../src/api/cityplan.ts'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8765'
const get = async (p) => { const r = await fetch(BASE + p); if (!r.ok) throw new Error(`${r.status} ${p}`); return r.json() }
const cases = [
  ['maiduguri', 2e9, 60, ['health', 'water', 'cold']], ['maiduguri', 1e9, 14, ['water', 'cold']], ['maiduguri', 1e13, 60, ['health', 'water', 'cold']],
  ['damaturu', 5e8, 40, ['health']], ['yola', 1e9, 60, ['health', 'cold']], ['maiduguri', 3e8, 7, ['water']], ['yola', 0, 14, ['health', 'water', 'cold']],
]
let bad = 0
for (const [city, budget, days, sectors] of cases) {
  const sites = await get(`/api/city/${city}/sites`)
  const ps = sites.features.map((f) => ({ ...f.properties, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] }))
  const api = await get(`/api/city/${city}/plan?budget_ngn=${budget}&days=${days}&sectors=${sectors.join(',')}`)
  const js = planCity(ps, budget, days, sectors, api.totals.diesel_ngn_per_l)
  const same = JSON.stringify(js.funded.map((r) => r.id)) === JSON.stringify(api.funded.map((r) => r.id))
  const near = (a, b, tol) => Math.abs(a - b) <= tol
  const ok = same && near(js.totals.spent_ngn, api.totals.spent_ngn, 1) && near(js.totals.share_with_funded ?? 0, api.totals.share_with_funded ?? 0, 1e-5)
    && near(js.totals.diesel_l_avoided, api.totals.diesel_l_avoided, 0.2)
  if (!ok) bad++
  console.log(ok ? 'same' : 'DIFF', city, budget, days, sectors.join('+'), js.totals.funded, api.totals.funded_count)
}
process.exit(bad ? 1 : 0)
