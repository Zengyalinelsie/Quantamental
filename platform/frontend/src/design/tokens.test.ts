import { describe, expect, it } from 'vitest'

import { tokens } from './tokens'

describe('institutional design tokens', () => {
  it('matches the visual source of truth in SPEC-043', () => {
    expect(tokens).toMatchObject({
      primary: '#2F5EA8',
      primaryHover: '#244C8A',
      layout: '#F3F5F7',
      container: '#FFFFFF',
      elevated: '#F7F8FA',
      subtle: '#ECEFF3',
      border: '#C8CDD4',
      secondaryBorder: '#DEE2E7',
      text: '#18202A',
      secondaryText: '#4E5968',
      tertiaryText: '#727D8B',
      borderRadius: 3,
    })
  })
})
