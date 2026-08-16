/**
 * Feature-local re-exports for the desk.
 *
 * The desk consumes only server projections, so its types come from the
 * generated API client rather than being redeclared here.  This module exists
 * so desk components import one stable path, matching how `features/screen`
 * groups its projection types.
 */
export type {
  DeskBlocker,
  DeskProjection,
  DeskSection,
  DeskSectionKey,
  DeskSectionStatus,
} from '../../api/client'
export type { WorkspaceStateKind } from '../../components/WorkspaceState'
