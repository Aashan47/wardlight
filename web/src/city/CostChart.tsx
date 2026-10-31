import type { CityMetrics, Num } from '../api/brief13'
import { OUTAGE_DAYS } from '../api/brief13'
import { LabelChip } from './bits'
import { compact, full, labelNote, labelOf, labelsFor, pt, rv, share, span, weakestOf } from './format'

interface CostRow { key: string; name: string; sub: string; cls: string; v: Num; lower?: Num; labelKeys: string[]; consts?: string[]; group: 'solar' | 'diesel' | 'gas' }

/** Cost per kWh delivered, naira, one axis. HTML, so text keeps its size on a phone. Every value is the API's. */
export function CostChart({ m, days }: { m: CityMetrics; days: number }) {
  const s = m.sustainability
  const c = s.cost_per_kwh_ngn
  const arms = s.cost_arms
  const tariff = s.gas_tariff_cost_reflective
  const rows: CostRow[] = [
    { key: 'plan', name: 'Solar plus storage, the plan', sub: 'outage-ready 7-day sizing, lifetime cost per kWh delivered', cls: 'b-solar', v: arms?.outage_ready_7d?.cost_per_kwh_ngn ?? c.solar, labelKeys: ['cost_solar'], consts: ['COST_', 'BATTERY_', 'OM_', 'SYSTEM_', 'REPLACEMENT_', 'FX_'], group: 'solar' },
    ...(arms?.daily_cycle ? [{ key: 'daily', name: 'Solar plus storage, daily cycle', sub: 'one day of PV and one night of battery, lifetime cost per kWh', cls: 'b-solar2', v: arms.daily_cycle.cost_per_kwh_ngn, labelKeys: ['cost_solar'], consts: ['COST_', 'BATTERY_', 'OM_', 'SYSTEM_', 'REPLACEMENT_', 'FX_'], group: 'solar' as const }] : []),
    { key: 'diesel', name: 'Diesel generator', sub: pt(c.diesel_fuel_only) !== null ? 'fuel, O&M and the set over its life; the tick marks fuel only' : 'fuel per kWh, plus generator costs where sourced', cls: 'b-diesel', v: c.diesel, lower: c.diesel_fuel_only, labelKeys: ['cost_diesel', 'diesel', 'diesel_price'], consts: ['GEN', 'DIESEL_'], group: 'diesel' },
    { key: 'gas_support', name: 'Gas plant (MEPP), federal operating support', sub: 'support alone per kWh it delivers, across a range of output', cls: 'b-gas', v: c.gas_support, labelKeys: ['gas_support', 'cost_gas_support'], consts: ['MEPP_SUPPORT', 'MEPP_AVG', 'MEPP_CAPACITY'], group: 'gas' },
    ...(pt(c.gas_tariff_cost_reflective) !== null || tariff?.ngn_per_kwh != null ? [{ key: 'gas_tariff', name: 'Gas plant (MEPP), cost-reflective tariff', sub: 'the plant\'s own cost per kWh it delivers', cls: 'b-gas2', v: c.gas_tariff_cost_reflective ?? tariff?.ngn_per_kwh, labelKeys: ['gas_tariff'], consts: ['MEPP_COST_TARIFF', 'MEPP_NBET', 'FX_'], group: 'gas' as const }] : []),
  ]
  const R = rows.map((r) => ({ ...r, r: rv(r.v), lo: pt(r.lower ?? null), label: weakestOf(m, r.labelKeys, r.consts) }))
  const plan = R[0].r.point
  const maxV = Math.max(1, ...R.flatMap((r) => [r.r.point ?? 0, r.r.hi ?? 0]))
  const step = niceStep(maxV / 4)
  const top = Math.ceil((maxV * 1.04) / step) * step
  const pc = (v: number) => `${(v / top) * 100}%`
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step)
  const be = rv(s.gas_breakeven_mwh_per_month), beMw = rv(s.gas_breakeven_mw)
  const support = typeof m.constants?.MEPP_SUPPORT_NGN_PER_MONTH?.value === 'number' ? m.constants.MEPP_SUPPORT_NGN_PER_MONTH.value : pt(s.gas_support_ngn_per_month)
  const position = s.gas_position?.text ?? m.headline_alongside
  const fuel = s.gas_position?.fuel ?? s.gas_fuel_note?.text
  const desc = R.map((r) => `${r.name}: ${r.r.point === null ? 'not available' : `N${full(r.r.point)} per kWh`}`).join('. ')

  return (
    <div className="costwrap">
      {position && (
        <p className="alongside" role="note"><span className="al-k">When the line is up</span>{position}</p>
      )}
      <figure className="costfig" aria-label={`Cost per kWh delivered, naira. ${desc}.`}>
        <div className="cost-plot" role="list">
          <div className="cost-grid" aria-hidden="true">
            {ticks.map((t) => <span key={t} style={{ left: pc(t) }} />)}
            {plan !== null && <span className="be" style={{ left: pc(plan) }}><em>the plan's cost per kWh</em></span>}
          </div>
          {R.map((r, i) => {
            const p = r.r.point
            const groupStart = i === 0 || R[i - 1].group !== r.group
            return (
              <div className={`cost-row${groupStart && i ? ' gstart' : ''}`} role="listitem" key={r.key} tabIndex={0}
                aria-label={`${r.name}, ${r.sub}: ${p === null ? 'not available' : `N${full(p)} per kWh`}${span(r.r, full) ? `, range ${span(r.r, full)}` : ''}${r.lo !== null ? `, fuel only N${full(r.lo)}` : ''}${r.label ? `, ${r.label}` : ''}`}>
                <div className="cost-head">
                  <span className={`key ${r.cls}`} aria-hidden="true" />
                  <strong>{r.name}</strong> <span className="muted small">{r.sub}</span>
                  <LabelChip label={r.label} note={labelsFor(m.labels, r.labelKeys).map(([, v]) => labelNote(v)).filter(Boolean).join('; ') || null} />
                </div>
                <div className="cost-track">
                  {p !== null && <span className={`bar ${r.cls}`} style={{ width: pc(p) }} />}
                  {r.r.lo != null && r.r.hi != null && r.r.hi > r.r.lo && <span className="whisk" style={{ left: pc(r.r.lo), width: `calc(${pc(r.r.hi)} - ${pc(r.r.lo)})` }} />}
                  {plan !== null && <span className="planmark" style={{ left: pc(plan) }} aria-hidden="true" />}
                  {r.lo !== null && <span className="lowtick" style={{ left: pc(r.lo) }} title={`fuel only: N${full(r.lo)} per kWh`} />}
                  <span className="val" style={{ left: `min(calc(${pc(Math.max(p ?? 0, r.r.hi ?? 0))} + 10px), calc(100% - 15ch))` }}>
                    {p === null ? 'not available' : <>N{full(p)}<small>/kWh</small></>}
                    {span(r.r, full) && <small className="muted"> {span(r.r, full)}</small>}
                  </span>
                </div>
              </div>
            )
          })}
          <div className="cost-axis" aria-hidden="true">{ticks.map((t) => <span key={t} style={{ left: pc(t) }}>N{compact(t)}</span>)}</div>
        </div>
        <figcaption>
          <p className="cap-strong">Support bar: operating support only; tariff and capital not included.</p>
          <p className="small muted" style={{ margin: 0 }}>
            {support !== null && <>The support bar divides N{compact(support)} a month of federal operating support by the plant's output. </>}
            {tariff?.usc_per_kwh != null && <>The tariff bar is the plant's cost-reflective tariff, {tariff.usc_per_kwh} US cents per kWh{tariff.nbet_paid_usc_per_kwh != null ? ` (the bulk buyer paid ${tariff.nbet_paid_usc_per_kwh})` : ''}{tariff.fx_ngn_per_usd ? `, at N${full(tariff.fx_ngn_per_usd)} per US dollar` : ''}{tariff.fx_date ? ` (${tariff.fx_date})` : ''}. </>}
            {be.point !== null && <>Below {beMw.point !== null ? `${beMw.point.toFixed(1)} MW average delivered (${full(be.point)} MWh a month)` : `${full(be.point)} MWh a month`}, the support alone would cost more per kWh than the plan's solar. </>}
            {fuel && <>{fuel} </>}
          </p>
          <details className="tableview">
            <summary>Show as a table, with sources</summary>
            <div className="table-scroll">
              <table className="table">
                <thead><tr><th>Option</th><th>N per kWh</th><th>Range</th><th>Label</th></tr></thead>
                <tbody>
                  {R.map((r) => (
                    <tr key={r.key}><td>{r.name}</td><td className="mono">{r.r.point === null ? 'n/a' : full(r.r.point)}{r.lo !== null ? ` (fuel only ${full(r.lo)})` : ''}</td><td className="mono">{span(r.r, full) ?? ''}</td><td>{r.label ?? labelOf(labelsFor(m.labels, r.labelKeys)[0]?.[1]) ?? ''}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            {tariff?.source && <p className="small muted">Tariff: {tariff.source}</p>}
            {s.gas_position?.fuel_source && <p className="small muted">Fuel: {s.gas_position.fuel_source}</p>}
          </details>
        </figcaption>
      </figure>

      {arms?.outage_ready_7d && arms.daily_cycle && <CostArms m={m} days={days} />}
    </div>
  )
}

/** The two sizing rules side by side: what each costs per kWh and what it keeps through 14, 40 and 60 days. */
function CostArms({ m, days }: { m: CityMetrics; days: number }) {
  const a = m.sustainability.cost_arms!
  const arms = [
    { key: 'outage_ready_7d' as const, name: 'Outage-ready 7-day', tag: 'the plan', arm: a.outage_ready_7d! },
    { key: 'daily_cycle' as const, name: 'Daily cycle', tag: 'cost arm only', arm: a.daily_cycle! },
  ]
  return (
    <div className="arms">
      <h3>Two ways to size the same systems</h3>
      <div className="arms-grid">
        {arms.map(({ key, name, tag, arm }) => {
          const c = rv(arm.cost_per_kwh_ngn)
          return (
            <article key={key} className={`arm${key === 'outage_ready_7d' ? ' plan' : ''}`}>
              <header className="row between"><strong>{name}</strong><span className="small muted">{tag}</span></header>
              <p className="arm-cost"><b>N{full(c.point)}</b><small>/kWh</small>{span(c, full) && <span className="rangeline"> range {span(c, full)}</span>}</p>
              <table className="arm-t">
                <caption className="sr-only">Critical service-hours kept with the {name} sizing</caption>
                <thead><tr><th scope="col">Outage</th><th scope="col">Hours kept</th><th scope="col">Share</th></tr></thead>
                <tbody>
                  {OUTAGE_DAYS.map((d) => {
                    const h = arm.csh?.[String(d)]
                    return (
                      <tr key={d} className={d === days ? 'cur' : ''}>
                        <th scope="row">{d} days</th>
                        <td className="mono">{h ? `${compact(h.with)} of ${compact(h.needed)}` : 'n/a'}</td>
                        <td><span className="mini"><span style={{ width: `${(h?.share ?? 0) * 100}%` }} /></span><span className="mono">{h ? share(h.share) : ''}</span></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {arm.label && <p className="small muted" style={{ margin: '8px 0 0' }}>{arm.label[0].toUpperCase() + arm.label.slice(1)}.</p>}
            </article>
          )
        })}
      </div>
      <p className="arms-note">
        <LabelChip label="ASSUMPTION" note={a.labels?.pricing ?? null} />
        <span>Battery cost is priced through PV size only, because no battery price is verified. A smaller battery therefore barely lowers the capital cost here, so the daily-cycle arm saves little money while keeping fewer hours.{a.labels?.pricing ? <span className="muted"> Engine note: {a.labels.pricing}.</span> : null}</span>
      </p>
    </div>
  )
}

function niceStep(raw: number) {
  const p = 10 ** Math.floor(Math.log10(Math.max(raw, 1e-9)))
  const f = raw / p
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p
}
