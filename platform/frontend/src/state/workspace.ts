import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface WorkspaceState {
  desktopCollapsed: boolean
  mobileDrawerOpen: boolean
  securityQuery: string
  universeId: string | null
  systemAsOf: string | null
  setDesktopCollapsed: (value: boolean) => void
  setMobileDrawerOpen: (value: boolean) => void
  setSecurityQuery: (value: string) => void
  setUniverseId: (value: string | null) => void
  setSystemAsOf: (value: string | null) => void
  reset: () => void
}

const initialState = {
  desktopCollapsed: false,
  mobileDrawerOpen: false,
  securityQuery: '',
  universeId: null,
  systemAsOf: null,
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      ...initialState,
      setDesktopCollapsed: (desktopCollapsed) => set({ desktopCollapsed }),
      setMobileDrawerOpen: (mobileDrawerOpen) => set({ mobileDrawerOpen }),
      setSecurityQuery: (securityQuery) => set({ securityQuery }),
      setUniverseId: (universeId) => set({ universeId }),
      setSystemAsOf: (systemAsOf) => set({ systemAsOf }),
      reset: () => set(initialState),
    }),
    {
      name: 'fq-workspace-preferences',
      partialize: ({ desktopCollapsed }) => ({ desktopCollapsed }),
    },
  ),
)
