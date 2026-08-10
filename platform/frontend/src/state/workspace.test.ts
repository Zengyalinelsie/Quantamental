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

  it('tracks API system time without persisting a fake default', () => {
    expect(useWorkspaceStore.getState().systemAsOf).toBeNull()
    useWorkspaceStore.getState().setSystemAsOf('2026-08-10T04:00:00Z')
    expect(useWorkspaceStore.getState().systemAsOf).toBe('2026-08-10T04:00:00Z')
    useWorkspaceStore.getState().reset()
    expect(useWorkspaceStore.getState().systemAsOf).toBeNull()
  })
})
