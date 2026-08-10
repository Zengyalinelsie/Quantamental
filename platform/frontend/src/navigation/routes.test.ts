import { describe, expect, it } from 'vitest'

import { primaryNavigation } from './routes'

describe('primary navigation contract', () => {
  it('contains exactly the six SPEC-046 destinations in order', () => {
    expect(primaryNavigation.map(({ path, label }) => ({ path, label }))).toEqual([
      { path: '/desk', label: '今日工作台' },
      { path: '/research', label: '研究' },
      { path: '/factors', label: '因子' },
      { path: '/portfolios', label: '组合' },
      { path: '/monitoring', label: '监控' },
      { path: '/system', label: '数据与管理' },
    ])
  })
})
