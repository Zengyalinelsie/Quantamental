import type { InvestmentViewProjection } from '../features/investment-view/investmentViewProjection'
import type {
  AlphaModelReadinessProjection,
  ScreenRankingProjection,
} from '../features/screen/screenProjection'
import type { IdentityProjection } from './schema'

export interface ResponseContext {
  as_of: string
  system_as_of: string
  data_mode: 'current_research' | 'strict_historical'
  deployment_stage: 'research' | 'shadow' | 'paper' | 'limited_live'
  trust_state: string | null
  dataset_version_ids: string[]
  model_version_ids: string[]
  run_id: string | null
  coverage: Record<string, unknown>
  warnings: string[]
}

export interface Envelope<T> {
  data: T
  context: ResponseContext
}

export interface ResearchWorkspaceBlocker {
  code: string
  reason: string
  affected_binding: string
  evidence_ids: string[]
}

export interface ResearchWorkspaceData {
  status: 'ready' | 'partial' | 'unavailable'
  blockers: ResearchWorkspaceBlocker[]
  screen: ScreenRankingProjection | null
  investment_view: InvestmentViewProjection | null
  alpha_model: AlphaModelReadinessProjection
}

export interface ArtifactMetadataProjection {
  artifact_id: string
  run_id: string
  content_hash: string
  media_type: string
  created_at: string
  producer_context: {
    data_mode: ResponseContext['data_mode']
    deployment_stage: ResponseContext['deployment_stage']
  }
}

export interface UniverseVersion {
  universe_version_id: string
  definition_id: string
  dataset_version_id: string
  created_at: string
}

export interface UniverseRow {
  listing_id: string
  company_id: string | null
  security_id: string | null
  exchange: 'XSHG' | 'XSHE' | 'XBSE' | null
  board: 'main' | 'star' | 'chinext' | 'bse' | null
  code: string | null
  name: string | null
  listed_on: string | null
  delisted_on: string | null
  industry_name: string | null
  listing_state: 'active' | 'suspended_listing' | 'terminated' | null
  special_treatment: 'none' | 'st' | 'star_st' | null
  research_eligible: boolean
  tradable_eligible: boolean
  inclusion_reasons: string[]
  exclusion_reasons: string[]
  benchmark_member: boolean
  identity_resolved: boolean
}

export interface UniverseSnapshot {
  universe_version_id: string
  dataset_version_id: string
  as_of: string
  rows: UniverseRow[]
}

export interface UniverseCoverage {
  universe_version_id: string
  as_of: string
  total_members: number
  identity_resolved: number
  research_eligible: number
  tradable_eligible: number
  identity_coverage: number | null
}

export interface DatasetCatalogEntry {
  dataset_version_id: string
  content_hash: string
  created_at: string
  schema_version: string
  metadata: Record<string, unknown>
}

export interface QualityReportEntry {
  quality_report_id: string
  dataset_version_id: string
  job_id: string
  status: 'passed' | 'warned' | 'failed'
  checks_passed: number
  checks_failed: number
  issue_counts: Record<string, number>
  warnings: string[]
  created_at: string
}

export interface CoverageReportEntry {
  coverage_report_id: string
  dataset_version_id: string
  job_id: string
  scope_id: string
  data_domain: string
  start_date: string
  end_date: string
  expected_rows: number | null
  observed_rows: number
  coverage_ratio: number | null
  warnings: string[]
  created_at: string
}

export interface LineageCatalogEntry {
  upstream_id: string
  downstream_id: string
  relation: string
}

export interface IngestionCheckpointEntry {
  checkpoint_key: string
  scope_id: string
  data_domain: string
  market: string | null
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  processed_rows: number
  rejected_rows: number
  provider_id: string | null
  updated_at: string
  error: string | null
  warnings: string[]
}

export interface IngestionJobEntry {
  job_id: string
  plan_id: string
  provider_id: string
  status: 'planned' | 'blocked' | 'running' | 'succeeded' | 'failed'
  output_trust_state: 'raw' | 'normalized_current' | 'pit_verified'
  start_date: string
  end_date: string
  created_at: string
  updated_at: string
  dataset_version_id: string | null
  failure_reasons: string[]
  checkpoints: IngestionCheckpointEntry[]
  quality_reports: QualityReportEntry[]
  coverage_reports: CoverageReportEntry[]
}

export interface RawEvidenceEntry {
  raw_object_id: string
  object_kind: 'request' | 'response' | 'file'
  content_hash: string
  source_url: string
  provider_id: string
  retrieved_at: string
  media_type: string
  license_id: string
  retention_policy: 'indefinite' | 'until_date' | 'metadata_only'
  retention_until: string | null
  redistribution_allowed: boolean
}

export interface DisclosureTimelineEntry {
  disclosure_id: string
  document_key: string
  external_document_id: string
  company_id: string
  security_id: string | null
  source_system: string
  title: string
  document_type: string
  report_period_end: string | null
  published_at: string
  available_at: string
  first_tradable_at: string
  publication_time_precision: 'exact' | 'date_only'
  version_sequence: number
  status: 'published' | 'corrected' | 'withdrawn'
  raw_object_id: string
  supersedes_disclosure_id: string | null
  status_reason: string | null
}

export interface FactRevisionEntry {
  fact_id: string
  company_id: string
  security_id: string
  metric_code: string
  value: string | number | boolean
  unit: string
  currency: string | null
  report_period_end: string
  period_type: string
  statement_type: string
  announced_at: string
  available_at: string
  known_from: string
  known_to: string | null
  revision_sequence: number
  provider_id: string
  source_field: string
  trust_state: 'raw' | 'normalized_current' | 'pit_verified'
  quality_state: 'passed' | 'warning' | 'blocked' | 'unavailable'
  mapping_version_id: string
  source_object_id: string
  dataset_version_id: string
  quality_issue_ids: string[]
}

export interface FactSelectionEntry {
  status: 'selected' | 'unavailable' | 'blocked'
  selected: FactRevisionEntry | null
  conflicting_fact_ids: string[]
  quality_issue_ids: string[]
  blocks_downstream: boolean
  reason: string | null
}

export interface FactComparisonEntry {
  company_id: string
  security_id: string
  metric_code: string
  report_period_end: string
  period_type: string
  statement_type: string
  decision_time: string
  system_time: string
  authority_rule_version: string
  current: FactSelectionEntry
  strict: FactSelectionEntry
}

export interface FinancialMismatchEntry {
  mismatch_id: string
  mismatch_type: string
  status: string
  company_id: string | null
  security_id: string | null
  metric_code: string | null
  report_period_end: string | null
  provider_ids: string[]
  related_ids: string[]
  reason: string
}

export interface ExperimentFeatureBindingEntry {
  feature_id: string
  version: string
  definition_hash: string
}

export interface ExperimentParameterEntry {
  name: string
  value: string
}

export interface ExperimentMetricEntry {
  name: string
  version: string
  value: string | number
  unit: string
}

export interface ExperimentFailureEntry {
  stage: string
  error_type: string
  message: string
  occurred_at: string
  retryable: boolean
}

export interface ExperimentRunEntry {
  run_id: string
  status: 'planned' | 'running' | 'succeeded' | 'failed'
  spec: {
    spec_id: string
    research_question: string
    run_context: {
      data_mode: 'current_research' | 'strict_historical'
      deployment_stage: 'research' | 'shadow' | 'paper' | 'limited_live'
    }
    feature_bindings: ExperimentFeatureBindingEntry[]
    parameters?: ExperimentParameterEntry[]
  }
  metrics: ExperimentMetricEntry[]
  failure: ExperimentFailureEntry | null
}

export type SystemSection = 'catalog' | 'quality' | 'lineage' | 'jobs'

export interface SystemSectionData {
  catalog: DatasetCatalogEntry[]
  quality: QualityReportEntry[]
  lineage: LineageCatalogEntry[]
  jobs: IngestionJobEntry[]
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
  }
}

export async function getEnvelope<T>(path: string, signal?: AbortSignal): Promise<Envelope<T>> {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, signal })
  const payload = await response.json()
  if (!response.ok) {
    throw new ApiError(response.status, payload.detail ?? `API request failed: ${response.status}`)
  }
  return payload as Envelope<T>
}

export function getUniverseVersions(signal?: AbortSignal) {
  return getEnvelope<UniverseVersion[]>('/api/universes', signal)
}

export function getUniverseSnapshot(universeId: string, asOf: string, signal?: AbortSignal) {
  return getEnvelope<UniverseSnapshot>(
    `/api/universes/${encodeURIComponent(universeId)}/snapshot?as_of=${encodeURIComponent(asOf)}`,
    signal,
  )
}

export function getUniverseCoverage(universeId: string, asOf: string, signal?: AbortSignal) {
  return getEnvelope<UniverseCoverage>(
    `/api/universes/${encodeURIComponent(universeId)}/coverage?as_of=${encodeURIComponent(asOf)}`,
    signal,
  )
}

export function getSystemSection<S extends SystemSection>(section: S, signal?: AbortSignal) {
  return getEnvelope<SystemSectionData[S]>(`/api/system/${section}`, signal)
}

export function getDisclosures(companyId: string, signal?: AbortSignal) {
  return getEnvelope<DisclosureTimelineEntry[]>(
    `/api/system/disclosures?company_id=${encodeURIComponent(companyId)}`,
    signal,
  )
}

export function getFactRevisions(params: URLSearchParams, signal?: AbortSignal) {
  return getEnvelope<FactRevisionEntry[]>(`/api/system/facts/revisions?${params}`, signal)
}

export function getFactComparison(params: URLSearchParams, signal?: AbortSignal) {
  return getEnvelope<FactComparisonEntry>(`/api/system/facts/compare?${params}`, signal)
}

export function getFinancialMismatches(signal?: AbortSignal) {
  return getEnvelope<FinancialMismatchEntry[]>('/api/system/mismatches', signal)
}

export function getExperimentRuns(signal?: AbortSignal) {
  return getEnvelope<ExperimentRunEntry[]>('/api/experiments/runs', signal)
}

export function getResearchWorkspace(securityId?: string, signal?: AbortSignal) {
  const query = securityId === undefined || securityId === ''
    ? ''
    : `?security_id=${encodeURIComponent(securityId)}`
  return getEnvelope<ResearchWorkspaceData>(`/api/research/workspace${query}`, signal)
}

export function getIdentity(signal?: AbortSignal) {
  return getEnvelope<IdentityProjection>('/api/identity', signal)
}

export function getArtifactMetadata(artifactId: string, signal?: AbortSignal) {
  return getEnvelope<ArtifactMetadataProjection>(
    `/api/artifacts/${encodeURIComponent(artifactId)}`,
    signal,
  )
}

export function getRawEvidence(rawObjectId: string, signal?: AbortSignal) {
  return getEnvelope<RawEvidenceEntry>(
    `/api/system/evidence/${encodeURIComponent(rawObjectId)}`,
    signal,
  )
}
