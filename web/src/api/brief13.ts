// Brief 13 API contract (14-SUCCESS-METRICS.md, "API contract"). The engine stream serves these endpoints:
//   GET /api/city/{city}/metrics?days=14|40|60
//   GET /api/city/{city}/sites            GeoJSON of every critical site
//   GET /api/corridor                     GeoJSON of the 330/132 kV lines, towers, substations, plants
//   GET /api/sites/{id}/siting            the siting card
// Numbers may arrive as a bare number or as {point, lo, hi}; `rv()` in ../city/format.ts reads both, so the UI does
// not depend on which one the engine chooses. Optional fields are read when present and never filled in by the UI.
import type { Feature, FeatureCollection, LineString, MultiLineString, Point, Polygon } from 'geojson'
import type { Source } from './types'

/** a source as the engine sends it ({text, url, status}), read into the app's Source shape plus its status */
export interface B13Source extends Source { status?: string }

export type CityId = 'maiduguri' | 'damaturu' | 'yola'
export const CITIES: { id: CityId; name: string; state: string }[] = [
  { id: 'maiduguri', name: 'Maiduguri', state: 'Borno' },
  { id: 'damaturu', name: 'Damaturu', state: 'Yobe' },
  { id: 'yola', name: 'Yola', state: 'Adamawa' },
]
export const OUTAGE_DAYS = [14, 40, 60] as const
export type OutageDays = (typeof OUTAGE_DAYS)[number]
export const DEFAULT_DAYS: OutageDays = 60 // the brief's starter question 1: "two months"

export type Sector = 'health' | 'water' | 'cold'
export const SECTORS: Sector[] = ['health', 'water', 'cold']
export type EvidenceLabel = 'VERIFIED' | 'ASSUMPTION' | 'UNVERIFIED'
export type RoofFit = 'fits' | 'partial' | 'ground' | 'unknown'

export interface Range { point: number | null; lo?: number | null; hi?: number | null; unit?: string; label?: EvidenceLabel | string; note?: string }
/** A figure as the API may send it. */
export type Num = number | Range | null | undefined
export type LabelValue = EvidenceLabel | string | { label: EvidenceLabel | string; note?: string; source?: string; url?: string }

export interface SectorImpact {
  sites?: number; csh_needed?: Num; csh_today?: Num; csh_today_diesel?: Num; csh_with?: Num
  diesel_l_avoided?: Num; kw?: Num; note?: string
}

export interface OwnershipRow {
  sector: Sector | string; owns: string; pays: string; guards: string; repairs: string
  model?: string; precedent?: string; label?: LabelValue; source?: string; url?: string
}
export interface FundingRow { source: string; covers: string; amount_ngn?: Num; terms?: string; label?: LabelValue; note?: string; url?: string }

/** one sizing rule priced over the system life, with the critical service-hours it keeps per outage length */
export interface CostArm {
  cost_per_kwh_ngn: Num; capex_ngn?: Num; lifecycle_ngn?: Num; lifetime_kwh?: Num; label?: string
  csh?: Record<string, { needed: number; with: number; share: number }>
  by_sector?: Partial<Record<Sector, { cost_per_kwh_ngn?: Num; csh?: Record<string, { needed: number; with: number; share: number }> }>>
}
/** today versus with the plan, as the engine sends some figures */
export interface TodayWith { today?: Num; with?: Num }
/** one input constant the engine run used, with its evidence status */
export interface Constant { value: number | string | null; lo?: number | null; hi?: number | null; unit?: string; status?: string; source?: string }

export interface CityMetrics {
  city: CityId; city_name?: string; name?: string; state?: string; lgas?: string[]; days: number; data_version?: string; headline?: string
  /** computed sentence: the gas plant is cheaper per kWh when it runs; the plan works alongside it */
  headline_alongside?: string
  /** true on synthetic files; the UI then marks every figure */
  sample?: boolean
  /** set only by the web app's own typed mock (brief13-mock.ts), never by the engine */
  mock?: boolean
  impact: {
    csh_needed: Num; csh_today: Num; csh_today_diesel: Num; csh_with: Num
    by_sector: Partial<Record<Sector, SectorImpact>>
    diesel_l_avoided: Num; diesel_ngn_avoided: Num
    diesel_l_avoided_per_year?: Num
    share_today?: number; share_with?: number; share_today_diesel?: number
    today_diesel_scenario?: { litres?: Num; ngn?: Num }
    water_m3_per_day_kept?: Num | TodayWith; people_served?: Num | TodayWith; people_note?: string
    cold_rooms_kept?: Num
  }
  innovation: {
    local_share: Num | (TodayWith & { critical_kwh_needed?: number }); sites: number; new_line_km: number
    sites_by_sector?: Partial<Record<Sector, number>>
    corridor: { km_330: Num; towers: Num; km_132?: Num; substations?: number; source?: string; box?: string; applies_to_city?: boolean; note?: string | null }
    community_owned_sites?: number; note?: string
  }
  sustainability: {
    cost_per_kwh_ngn: { solar: Num; diesel: Num; gas_support: Num; gas_tariff_cost_reflective?: Num; diesel_fuel_only?: Num }
    cost_arms?: { outage_ready_7d?: CostArm; daily_cycle?: CostArm; sites?: number; labels?: Record<string, string> }
    gas_tariff_cost_reflective?: { ngn_per_kwh?: number; usc_per_kwh?: number; nbet_paid_ngn_per_kwh?: number; nbet_paid_usc_per_kwh?: number; fx_ngn_per_usd?: number; fx_date?: string; source?: string; label?: string }
    gas_position?: { gas_cheaper_when_running?: boolean; text?: string; brief_constraint?: string; fuel?: string; fuel_source?: string }
    gas_fuel_note?: { text?: string; source?: string }
    /** the output range the gas support per kWh is computed over */
    gas_output_mwh_per_month?: { lo: number; hi: number } | Range
    gas_support_ngn_per_month?: Num
    gas_breakeven_mwh_per_month: Num
    gas_breakeven_mw?: Num
    /** support per kWh at a stated average delivered output, keyed by MW */
    gas_support_at_mw?: Record<string, number>
    solar_by_sector?: Partial<Record<Sector, Num>>
    capex_ngn?: Num
    co2_t_avoided: Num; co2_t_avoided_per_year?: Num; co2_t_avoided_per_year_upper?: Num
    cost_labels?: Record<string, string>
    ownership: OwnershipRow[]
    funding?: FundingRow[]
    notes?: Record<string, string>
  }
  feasibility: {
    roof_fit: { fits: number; partial: number; ground: number; unknown?: number }
    sites?: number; new_line_km?: number; median_corridor_km?: Num; min_corridor_km?: Num; km_to_330kv_median?: Num
    security?: (string | AntiTheft)[]; battery_kwh_total?: Num
    serviceable_locally?: string[]; note?: string
  }
  scalability?: { plan_minutes?: Num; build_seconds?: number; cities?: string[]; checklist?: string[]; another_city_needs?: string[]; data?: Record<string, string>; note?: string }
  excluded?: { existing_onsite?: { id: string; name: string; note?: string }[]; [k: string]: unknown }
  labels: Record<string, LabelValue>
  /** input constants with their status (the engine nests them under labels.constants; the normalizer lifts them) */
  constants?: Record<string, Constant>
  methods?: Record<string, string>
  sources: B13Source[]
}

export interface SiteResult {
  needed_h?: number | null; today_h?: number | null; today_diesel_h?: number | null; with_h?: number | null
  share_today?: number | null; share_with?: number | null; diesel_l_avoided?: Num
}
export interface SitingSummary { roof_fit?: RoofFit; fit?: RoofFit; roof_kwp?: number | null; km_to_330kv?: number | null; pv_kwp?: number | null; battery_kwh?: number | null; corridor_km?: number | null; new_line_km?: number | null }
export interface SiteProps {
  id: string; name: string; sector: Sector; archetype?: string; lga?: string
  in_plan?: boolean; existing_onsite?: boolean; kw_range?: [number, number] | null; m3_day?: number | null; hours_per_day?: number | null; supply?: string
  system?: { pv_kwp?: number | null; battery_kwh?: number | null; capex_ngn?: number | null }
  labels?: Record<string, LabelValue> | null; note?: string | null
  /** critical load, kW */
  kw?: number | null; kwh_day?: number | null
  /** the API's ranked order for the plan; the lowest rank is the default site */
  rank?: number | null
  planned?: boolean
  /** GRID3 id for a health site, which the 3D outage night can run */
  facility_id?: string | null
  existing_solar?: boolean
  /** "api" when the engine sent rank, "rule" when the web app ordered by the engine's /api/city rule */
  rank_source?: 'api' | 'rule'
  /** keyed by outage days ("14", "40", "60"), or one flat block */
  results?: Record<string, SiteResult> | SiteResult
  share_today?: number | null; share_with?: number | null
  siting?: SitingSummary
  owner?: string; label?: LabelValue
}
export type SitesFC = FeatureCollection<Point, SiteProps> & { city?: CityId; sample?: boolean; mock?: boolean; sources?: B13Source[]; properties?: { rank_rule?: string; facility_id?: string } }

export type CorridorKind = 'line' | 'tower' | 'substation' | 'plant' | 'generator' | 'pole'
export interface CorridorProps {
  kind?: CorridorKind | string; power?: string; voltage_kv?: number | null; voltage?: string | number
  name?: string; operator?: string; plant_source?: string; source?: string; capacity_mw?: number | null
  osm_id?: string | number; note?: string; part_of_plan?: boolean
}
export type CorridorFeature = Feature<LineString | MultiLineString | Point | Polygon, CorridorProps>
export type CorridorFC = FeatureCollection<LineString | MultiLineString | Point | Polygon, CorridorProps> & {
  sample?: boolean; mock?: boolean; km_330?: number; towers?: number; sources?: Source[]; retrieved?: string
}

export interface AntiTheft { measure: string; detail?: string; source?: string; url?: string; label?: LabelValue; basis?: string; status?: string }
export interface Siting {
  id: string; name: string; sector: Sector; archetype?: string; city?: CityId; lga?: string
  sample?: boolean; mock?: boolean
  pv_kwp_needed: Num; roof_kwp_available?: Num; roof_area_m2?: Num; buildings?: number; placement?: string; existing_onsite?: boolean
  roof_fit: RoofFit
  battery_kwh: Num; battery_room?: string
  new_line_km: number
  corridor_km: Num
  anti_theft: (AntiTheft | string)[]
  ownership?: OwnershipRow
  serviceable_locally?: string[]
  labels?: Record<string, LabelValue>
  sources?: B13Source[]
  notes?: string[]
}

/** Where a payload came from. "mock" is the web app's own placeholder and is always marked on screen. */
export type DataSource = 'live' | 'fixture' | 'mock'
export interface Sourced<T> { data: T; src: DataSource }

/** GET /api/sites/{id}/outage_trace?days=: one simulated outage, hourly, for any sector. Health sites carry rooms;
    water and cold sites carry needed / served shares. */
export interface SiteTrace {
  days: number; site_id?: string; sector?: Sector; archetype?: string; name?: string
  hour_index: number[]; hour: number[]; in_outage: boolean[]; grid_on: boolean[]; solar_kw: number[]; load_kw: number[]; battery_soc: number[]
  pv_kwp: number; battery_kwh: number; kw?: number; mode?: string
  needed?: boolean[]; served_with?: (number | null)[]; served_today?: (number | null)[]; existing_array_kw?: number[]; served_rule?: string
  rooms?: Partial<Record<'fridge' | 'delivery' | 'oxygen' | 'lab' | 'ward', (boolean | null)[] | null>>
  rooms_today?: Partial<Record<'fridge' | 'delivery' | 'oxygen' | 'lab' | 'ward', (boolean | null)[] | null>>
  room_names?: Record<string, string>; scenario?: string; note?: string
  draw?: { lane: number; n_lanes: number; window_start_day?: number; lane_hours_kept?: number; median_hours_kept?: number; lane_service_hours_with?: number; median_service_hours_with?: number; rule?: string }
}
