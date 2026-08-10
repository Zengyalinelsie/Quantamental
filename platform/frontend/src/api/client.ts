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
