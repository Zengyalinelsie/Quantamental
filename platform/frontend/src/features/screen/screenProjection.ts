export type ScreenDataMode = 'current_research' | 'strict_historical'
export type ScreenTrustState = 'normalized_current' | 'pit_verified'
export type ScreenDeploymentStage = 'research' | 'shadow' | 'paper' | 'limited_live'
export type ScreenApprovalScope = 'research_backtest' | 'shadow' | 'paper' | 'limited_live'

export interface ScreenProjectedValue {
  raw: string
  display: string
}

export interface ScreenRankProjection {
  value: number
  display: string
}

export interface ScreenNullableRankProjection {
  value: number | null
  display: string | null
  unavailable_reason: string | null
}

export interface ScreenRankChangeProjection extends ScreenNullableRankProjection {
  direction: 'up' | 'down' | 'flat' | 'unavailable'
}

export interface ScreenSecurityIdentityProjection {
  security_id: string
  symbol: string
  display_name: string
  exchange: string
}

export interface ScreenIndustryProjection {
  code: string
  display_name: string
}

export interface ScreenRankingRowProjection {
  snapshot_id: string
  security: ScreenSecurityIdentityProjection
  industry: ScreenIndustryProjection
  rank: ScreenRankProjection
  previous_rank: ScreenNullableRankProjection
  rank_change: ScreenRankChangeProjection
  score: ScreenProjectedValue
  expected_return: ScreenProjectedValue
  confidence: ScreenProjectedValue
  investment_view_id: string
  trust_state: ScreenTrustState
  content_hash: string
  /** Server-selected row. The UI does not infer selection from rank or URL state. */
  selected: boolean
}

export interface SelectedScreenSecurityProjection {
  security_id: string
  snapshot_id: string
  display_name: string
  symbol: string
  industry: ScreenIndustryProjection
}

export interface IndustryPeerProjection {
  security_id: string
  display_name: string
  symbol: string
  rank: ScreenRankProjection
  expected_return: ScreenProjectedValue
  snapshot_id: string
}

export interface ScreenRankingProjection {
  screen_id: string
  universe: {
    universe_version_id: string
    display_name: string
    universe_size: number
  }
  decision_time: string
  data_cutoff: string
  data_mode: ScreenDataMode
  trust_state: ScreenTrustState
  approval_scope: ScreenApprovalScope
  model_version_id: string
  factor_version_ids: string[]
  dataset_version_ids: string[]
  feature_version_ids: string[]
  /** Already ranked and paged by the serving API. Order is authoritative. */
  rows: ScreenRankingRowProjection[]
  selected_security: SelectedScreenSecurityProjection | null
  /** Server-projected industry peers. The UI does not derive peers from rows. */
  industry_peers: IndustryPeerProjection[]
  warnings: string[]
}

export interface AlphaReadinessBlockerProjection {
  code: string
  reason: string
  affected_binding: string
  evidence_ids: string[]
}

export interface ApprovedAlphaFactorProjection {
  factor_version_id: string
  factor_version_hash: string
  lifecycle_status: 'production'
  review_id: string
  review_hash: string
  validation_report_id: string
  validation_report_hash: string
  scientific_gate_passed: true
  approval: {
    approval_id: string
    approval_hash: string
    scope: ScreenApprovalScope
    decision: 'approved'
    reviewer_id: string
    reviewer_role: 'reviewer' | 'administrator'
    decided_at: string
    reason: string
  }
}

interface AlphaModelReadinessContextProjection {
  requested_scope: ScreenApprovalScope
  data_mode: ScreenDataMode
  deployment_stage: ScreenDeploymentStage
  checked_at: string
}

export type AlphaModelReadinessProjection =
  | (AlphaModelReadinessContextProjection & {
    status: 'unavailable'
    blocked_reasons: AlphaReadinessBlockerProjection[]
  })
  | (AlphaModelReadinessContextProjection & {
    status: 'ready'
    model: {
      model_version_id: string
      code_version: string
      content_hash: string
    }
    factors: ApprovedAlphaFactorProjection[]
  })
