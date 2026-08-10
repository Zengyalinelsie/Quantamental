import { describe, expect, it } from 'vitest'

import { parseUniverseView, updateUniverseView } from './universeView'

describe('universe URL view', () => {
  it('defaults to an unselected current view without inventing a universe', () => {
    expect(parseUniverseView(new URLSearchParams())).toEqual({
      universeId: null,
      pointMode: 'current',
      asOf: null,
      eligibility: null,
      industry: null,
      listingState: null,
      sort: null,
      order: null,
      hiddenColumns: [],
    })
  })

  it('round trips filters sort and column visibility through the URL', () => {
    const initial = new URLSearchParams('tab=universe-screen')
    const updated = updateUniverseView(initial, {
      universeId: 'universe-version:core-a-share:v1',
      pointMode: 'historical',
      asOf: '2020-05-22',
      eligibility: 'tradable',
      industry: '房地产业',
      listingState: 'active',
      sort: 'code',
      order: 'descend',
      hiddenColumns: ['board', 'benchmark_member'],
    })
    expect(updated.get('tab')).toBe('universe-screen')
    expect(parseUniverseView(updated)).toMatchObject({
      universeId: 'universe-version:core-a-share:v1',
      pointMode: 'historical',
      asOf: '2020-05-22',
      eligibility: 'tradable',
      industry: '房地产业',
      listingState: 'active',
      sort: 'code',
      order: 'descend',
      hiddenColumns: ['benchmark_member', 'board'],
    })
  })

  it('rejects invalid dates and enum values instead of forwarding them', () => {
    const view = parseUniverseView(
      new URLSearchParams('point=pretend-pit&as_of=yesterday&eligibility=yes&order=random'),
    )
    expect(view.pointMode).toBe('current')
    expect(view.asOf).toBeNull()
    expect(view.eligibility).toBeNull()
    expect(view.order).toBeNull()
  })
})
