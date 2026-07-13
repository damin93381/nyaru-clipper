import type { ReactNode } from "react";

import {
  ExistingReviewWorkspace,
  type ExistingReviewWorkspaceProps,
} from "../workstation/features/task-overview/ExistingReviewWorkspace";

export type WorkspacePageProps = ExistingReviewWorkspaceProps;

/**
 * Compatibility entry point for the legacy task-detail route.
 *
 * The workstation overview and the legacy detail page deliberately share the
 * same review behavior while their surrounding layouts continue to evolve.
 */
export function WorkspacePage(props: WorkspacePageProps): ReactNode {
  return <ExistingReviewWorkspace {...props} />;
}
