export type PointMode = 'current' | 'historical'
export type EligibilityFilter = 'research' | 'tradable'
export type SortOrder = 'ascend' | 'descend'

export interface UniverseView {
  universeId: string | null
  pointMode: PointMode
  asOf: string | null
  eligibility: EligibilityFilter | null
  industry: string | null
  listingState: string | null
  sort: string | null
  order: SortOrder | null
  hiddenColumns: string[]
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

function nullable(params: URLSearchParams, key: string) {
  const value = params.get(key)?.trim()
  return value ? value : null
}

export function parseUniverseView(params: URLSearchParams): UniverseView {
  const point = params.get('point')
  const asOf = nullable(params, 'as_of')
  const eligibility = params.get('eligibility')
  const order = params.get('order')
  return {
    universeId: nullable(params, 'universe'),
    pointMode: point === 'historical' ? 'historical' : 'current',
    asOf: asOf && ISO_DATE.test(asOf) ? asOf : null,
    eligibility: eligibility === 'research' || eligibility === 'tradable'
      ? eligibility
      : null,
    industry: nullable(params, 'industry'),
    listingState: nullable(params, 'listing_state'),
    sort: nullable(params, 'sort'),
    order: order === 'ascend' || order === 'descend' ? order : null,
    hiddenColumns: [...new Set(
      (params.get('hidden') ?? '').split(',').map((value) => value.trim()).filter(Boolean),
    )].sort(),
  }
}

export function updateUniverseView(
  current: URLSearchParams,
  patch: Partial<UniverseView>,
) {
  const next = new URLSearchParams(current)
  const merged = { ...parseUniverseView(current), ...patch }
  const values: Record<string, string | null> = {
    universe: merged.universeId,
    point: merged.pointMode === 'historical' ? 'historical' : null,
    as_of: merged.asOf,
    eligibility: merged.eligibility,
    industry: merged.industry,
    listing_state: merged.listingState,
    sort: merged.sort,
    order: merged.order,
    hidden: merged.hiddenColumns.length ? [...merged.hiddenColumns].sort().join(',') : null,
  }
  Object.entries(values).forEach(([key, value]) => {
    if (value) next.set(key, value)
    else next.delete(key)
  })
  return next
}
