import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const shellStyles = readFileSync('src/app/shell.less', 'utf8')

function rule(selector: string) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = shellStyles.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))
  expect(match, `missing CSS rule for ${selector}`).not.toBeNull()
  return match?.[1] ?? ''
}

describe('responsive application layout contract', () => {
  it('closes the fixed desktop navigation and main content widths within the viewport', () => {
    expect(rule('.mainLayout')).toContain('width: calc(100vw - 280px)')
    expect(rule('.ant-layout-has-sider > .desktopSider.ant-layout-sider-collapsed + .mainLayout'))
      .toContain('width: calc(100vw - 72px)')
  })

  it('allows long run-context values to shrink and wrap instead of clipping the right edge', () => {
    expect(rule('.contextItem')).toContain('min-width: 0')
    expect(rule('.contextItem strong')).toContain('overflow-wrap: anywhere')
  })

  it('keeps Universe controls inside their responsive container', () => {
    expect(rule('.universeControls')).toContain('flex-wrap: wrap')
    expect(rule('.universeControls label')).toContain('max-width: 100%')
    expect(rule('.universeControls .ant-select')).toContain('min-width: 0')
    expect(rule('.universeControls .ant-select')).toContain('width: 100%')
  })
})
