import { beforeEach, describe, expect, it } from 'vitest'

import { useWorkspaceStore } from './workspace'

describe('workspace state', () => {
  beforeEach(() => {
    useWorkspaceStore.getState().reset()
  })

  it('never defaults to a fixture security', () => {
    expect(useWorkspaceStore.getState().securityQuery).toBe('')
    expect(useWorkspaceStore.getState().universeId).toBeNull()
  })

  it('keeps desktop collapse and mobile drawer as independent state', () => {
    useWorkspaceStore.getState().setDesktopCollapsed(true)
    expect(useWorkspaceStore.getState().desktopCollapsed).toBe(true)
    expect(useWorkspaceStore.getState().mobileDrawerOpen).toBe(false)
    useWorkspaceStore.getState().setMobileDrawerOpen(true)
    expect(useWorkspaceStore.getState().desktopCollapsed).toBe(true)
    expect(useWorkspaceStore.getState().mobileDrawerOpen).toBe(true)
  })
})
