import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { NumericCell } from './NumericCell'

describe('NumericCell', () => {
  it('formats finite values with tabular right-aligned numerals', () => {
    render(<NumericCell value={1234.5} precision={1} suffix="万元" />)
    const cell = screen.getByText('1,234.5万元')
    expect(cell).toHaveClass('numericCell')
  })

  it('renders missing values explicitly instead of zero', () => {
    render(<NumericCell value={null} unavailableReason="尚无权威数据" />)
    expect(screen.getByLabelText('不可用：尚无权威数据')).toHaveTextContent('—')
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })
})
