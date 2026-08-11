export type InvestmentDataMode = 'current_research' | 'strict_historical'

export type InvestmentTrustState = 'normalized_current' | 'pit_verified'

export type InvestmentComponentName =
  | 'quality'
  | 'valuation'
  | 'revision'
  | 'event'

export type InvestmentComponentStatus =
  | 'quantified'
  | 'constrained'
  | 'unavailable'
  | 'not_applicable'

export interface ProjectedValue {
  /** Exact decimal representation retained for audit and export. */
  raw: string
  /** Server-formatted display value, including sign and unit. */
  display: string
}

export interface WaterfallVisualProjection {
  /** Precomputed by the serving projection. The UI does not derive coordinates. */
  start_percent: string
  width_percent: string
  direction: 'positive' | 'negative' | 'flat'
}

export interface InvestmentComponentProjection {
  component: InvestmentComponentName
  label: string
  status: InvestmentComponentStatus
  contribution: ProjectedValue | null
  reason: string
  evidence_ids: string[]
  visual: WaterfallVisualProjection | null
}

export interface ResidualProjection {
  status: InvestmentComponentStatus
  contribution: ProjectedValue | null
  reason: string
  evidence_ids: string[]
  visual: WaterfallVisualProjection | null
}

export interface ClosureProjection {
  status: 'passed' | 'failed' | 'unavailable'
  displayed_total: string | null
  tolerance: string
  difference: string | null
  checked_by: string
}

export interface ExpectedReturnDistributionProjection {
  point: ProjectedValue
  p10: ProjectedValue
  p50: ProjectedValue
  p90: ProjectedValue
  downside: ProjectedValue
}

export interface CatalystProjection {
  catalyst_id: string
  summary: string
  horizon: string
  evidence_ids: string[]
}

export interface InvalidatorProjection {
  invalidator_id: string
  summary: string
  evidence_ids: string[]
}

export interface InvestmentEvidenceProjection {
  evidence_id: string
  title: string
  source_kind: string
  available_at: string
  version: string
  source_url: string | null
}

export interface InvestmentViewVersionsProjection {
  dataset_version_ids: string[]
  feature_version_ids: string[]
  model_version_id: string
  run_id: string
  code_version: string
  environment_id: string
  content_hash: string
  artifact_id: string | null
}

export interface InvestmentViewProjection {
  view_id: string
  security: {
    security_id: string
    symbol: string
    exchange: string
    display_name: string
  }
  decision_time: string
  horizon: string
  data_mode: InvestmentDataMode
  trust_state: InvestmentTrustState
  trust_reason: string
  distribution: ExpectedReturnDistributionProjection
  components: InvestmentComponentProjection[]
  residual: ResidualProjection
  closure: ClosureProjection
  confidence: ProjectedValue
  catalysts: CatalystProjection[]
  invalidators: InvalidatorProjection[]
  evidence: InvestmentEvidenceProjection[]
  versions: InvestmentViewVersionsProjection
  warnings: string[]
}
