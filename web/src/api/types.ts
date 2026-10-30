// Types for the Wardlight API contract (06-PRODUCT-DESIGN.md). The fixtures in
// data/fixtures/web/ follow the same shapes, plus "sample": true on synthetic files.

export type Tier = 'a_named' | 'b_place' | 'c_lga_mixture' | 'c_unit_mixture' | 'd_refused' | 'offgrid'
export type Band = 'A' | 'B' | 'C' | 'D' | 'E'
export type RoomKey = 'fridge' | 'delivery' | 'oxygen' | 'lab' | 'ward'
export type FridgeMode = 'shared' | 'pqs_sdd'
export type FixCategory = 'pqs_icelined' | 'pqs_sdd' | 'solar_clinic'
export interface Fix { category: FixCategory; label: string; reason: string; cost_ngn: number; cost_note: string }
export interface Scenario { key: 'domestic' | 'pqs_icelined'; label: string; headline: boolean; uptime: Interval; note: string }

export interface Source { name: string; url: string; licence: string; retrieved: string }
export interface Health { ok: boolean; fixture: boolean; sample?: boolean; data_version: string; sources: Source[] }

export interface Interval { p: number; lo: number; hi: number }

export interface FacilityListItem extends CapFields, ScenarioFields {
  id: string; name: string; type: string; lat: number | null; lon: number | null
  state: string; lga: string; tier: Tier; p_fridge_survives: number | null; code?: number
}

export interface Facility extends CapFields {
  id: string; name: string; type: string; level: string; ownership: string
  state: string; lga: string; ward: string | null; lat: number | null; lon: number | null
  tier: Tier; feeder_id: string | null; band: Band | null; grid_km: number | null; catchment?: number | null; code?: number; source_version?: string; capped?: boolean
}

export interface Evidence {
  file: string | null; url: string | null; page: number | null; sn: number | null
  row_text: string | null; crop: string | null; verified: boolean; verified_note?: string; verified_by?: string; verified_how?: string; verified_method?: string; checked_by?: string | null; how?: string | null; check_result?: string | null; nerc_text?: string; facility_value?: string; matched_on?: string
}

export interface Match {
  tier: Tier; feeder_id: string | null; feeder_name?: string | null; disco?: string; band: Band | null
  bands: Partial<Record<Band, number>>; min_hours: number | null; promised_not_measured: boolean
  evidence: Evidence | null; reason: string
}

export interface SupplyModel { label: 'modelled'; promised_hours: number | null; median_hours: number | null; p10_hours: number | null; p90_hours: number | null; note: string }
export interface Load { key: RoomKey; name: string; priority: number; kw: number; hours: 'all' | 'night' | 'day'; source: string }
export interface LoadSurvival extends Interval { load: RoomKey; name: string; combined?: string; system?: string }

export interface HourlyTrace {
  start_hour: number
  hour: number[]
  grid_on: boolean[]
  solar_kw: number[]
  load_kw: number[]
  battery_soc: number[]
  fridge_c: number[]
  battery_kwh: number
  pv_kwp: number
  fridge_mode: FridgeMode
  fridge_curve: 'illustrative' | 'sourced'
  /** per room and hour: true powered, false dark, null not needed that hour */
  rooms: Record<RoomKey, (boolean | null)[]>
}

export interface Recommended {
  fridge_system: { design: string; holdover_h_range: [number, number]; note: string }
  clinic_system: { design: string; pv_kwp: number; battery_kwh: number }
  capex_usd: { lo: number; mid: number; hi: number }
  capex_ngn: { lo: number; mid: number; hi: number }
  monthly_cost_ngn: number; monthly_diesel_ngn: number; payback_months: number | null
  diesel_l_avoided: number; co2_kg_avoided: number; who_pays: string[]; maintains: string
  fix?: { label: string; model_name?: string; kind?: string; price_basis?: string; monthly_basis?: string }
  clinic_line?: { capex_usd?: { lo: number; mid: number; hi: number }; capex_ngn?: { lo: number; mid: number; hi: number } }
  lines_note?: string
}

export interface CostPoint { battery_kwh: number; pv_kwp: number; cost_usd: number; p_fridge: LoadSurvival }

export interface FacilityRecord {
  sample?: boolean
  facility: Facility
  match: Match
  refused?: boolean
  supply_model?: SupplyModel
  loads?: Load[]
  survival_today?: LoadSurvival[]
  survival_with_system?: LoadSurvival[]
  brief_metric?: {
    uptime_today: Interval; uptime_with_system: Interval; doses_year: number
    doses_protected_today: number; doses_protected_with_system: number; doses_note: string
  }
  recommended?: Recommended
  cost_curve?: CostPoint[]
  trace?: HourlyTrace & { scenario?: string; draw?: TraceDraw; note?: string }
  capped?: boolean
  fix?: Fix
  scenarios?: Scenario[]
  results_stale?: boolean; result_tier?: Tier; labels?: Record<string, string>; data_version?: string
}

export interface SimulateRequest { loads: RoomKey[]; pv_kwp: number; battery_kwh: number; target: number; fridge_mode: FridgeMode }
export interface SimulateResponse {
  pv_kwp: number; battery_kwh: number; survival: LoadSurvival[]; fridge_days?: Interval
  cost_usd: number; trace: HourlyTrace; sample?: boolean; snapped?: boolean
}

export interface PlanRow extends CapFields, ScenarioFields {
  id: string; name: string; lga: string; lat: number; lon: number; code?: number; tier: Tier; rank: number
  cost_ngn: number; cumulative_ngn: number; fridge_nights_saved: number; unmet_hours: number
  uptime_today: number; uptime_with_system: number; doses_protected_gain: number; score: number; reason: string; fix: FixCategory; capped?: boolean
}
export interface Plan { sample?: boolean; state: string; target: number; budget_ngn_max: number; currency_note: string; ranked: PlanRow[] }

export interface FeederRow { checked_by?: string | null; how?: string | null; verified_by?: string; verified_how?: string; verified_method?: string; file: string; url: string; page: number; sn: number; band: Band; feeder_name: string; location: string; streets?: string; min_hours: number; verified: boolean; crop?: string | null; order_month?: string; id?: string }
export interface Feeder {
  sample?: boolean; id: string; name: string; disco: string; band: Band | null; min_hours: number | null
  band_history: { order_file: string; order_month: string; band: Band; min_hours: number }[]
  history_note?: string
  rows: FeederRow[]
  facilities: { id: string; name: string; tier: Tier; how: string }[]
  served_summary?: ServedSummary
}

export interface Summary {
  sample?: boolean
  by_state: { state: string; total: number; tiers: Partial<Record<Tier, number>> }[]
  tiers: Partial<Record<Tier, number>>
  refusals: { reason: string; count: number }[]
  headline: { facilities: number; matched: number; refused: number }
  quotes: { text: string; source: string; url: string }[]
}

export interface ResultRow { id: string; what: string; target: string; result: string | null; status: 'not_run' | 'hit' | 'miss' | 'reported'; how?: string; source?: string }
export interface Results { sample?: boolean; prereg_url: string; rows: ResultRow[] }

// ---- additions served by the live API (docs/sources/api.md) ----
export interface TraceDraw {
  scenario: string; n_lanes: number; rule: string; lane: number; lane_uptime: number; run_median_uptime: number
  wanted_fridge_held: boolean; window_fridge_held: boolean; state_matched: boolean; nights_held_in_lane: number; nights_in_lane: number
  night_index: number; day_of_year: number; window_grid_hours: number; lane_median_grid_hours: number; headline_uptime: number; headline_source: string
}
export interface ServedSummary {
  facilities: number; by_tier: Partial<Record<Tier, number>>; by_level: Record<string, number>; hospitals: number; phcs: number; type_rule: string
  doses_year: number; doses_year_facilities: number; doses_year_shared_with_other_feeders: number; doses_note: string
  promised_hours: number | null; measured: { period?: string; measured_avg_hours?: number; gap_hours?: number; action?: string; file?: string; page?: number }[]; measured_note?: string
  disco_context?: { failing_band_a_rows_with_measured_hours: number; median_measured_avg_hours: number; band_a_promise_hours: number; median_gap_hours: number; label: string }
}
export interface BriefCitation { verified?: boolean; checked_by?: string | null; how?: string | null; kind: string; file?: string | null; url?: string | null; page?: number | null; sn?: string | number | null; row_text?: string | null; text: string }
export interface BriefRow extends CapFields, ScenarioFields {
  rank: number; id: string; code?: number; name: string; lga: string; type?: string; tier: Tier; fix: FixCategory; fix_label: string; fix_model?: string | null
  cost_ngn: number; cumulative_ngn: number; benefit: number; benefit_per_mngn?: number; doses_year?: number; doses_gain?: number
  uptime_today: number; uptime_with_fix: number; results_stale?: boolean; capped?: boolean; citation: BriefCitation
}
export interface Brief {
  kind: string; data_version: string; state: string; metric: string; benefit_unit: string; budget_ngn: number; target: number; currency_note: string
  funded: BriefRow[]
  totals: { funded: number; spent_ngn: number; left_ngn: number; benefit: number; doses_protected_today?: number; doses_protected_with_fix?: number; fixes?: Record<string, number>; spend_by_fix_ngn?: Record<string, number>; candidates?: number; facilities_in_state?: number; capped_funded?: number; capped_note?: string }
  not_reached: { group: string; count: number; why: string; cost_ngn_to_fund_all?: number; benefit_forgone?: number }[]
  method: string; scenarios: { key: string; headline: boolean; text: string }[]; labels: Record<string, string>
  assumptions: { name: string; value: number | string; lo?: number; hi?: number; unit?: string; status: string; source: string }[]
  sources: Source[]; staleness: { note: string | null; facilities_tier_changed_since_results?: number }
}

/** Catchment cap fields (engine doses.py): served on facility records, list items, plan rows and brief rows. */
export interface CapFields { capped?: boolean | null; catchment_pop?: number | null; pop_above_cap?: number | null; doses_demand_uncapped?: number | null }
/** Scenario wording for a bare uptime figure, when the API sends one; otherwise the headline scenario applies. */
export interface ScenarioFields { uptime_scenario?: string; scenario_label?: string; scenario?: string }
