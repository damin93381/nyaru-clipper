import type { components } from "../../../generated/api-schema";

import { getTaskOverview } from "../task-library/api";

export type WorkstationTaskOverview = components["schemas"]["TaskOverview"];

export function getWorkstationTaskOverview(taskId: string): Promise<WorkstationTaskOverview> {
  return getTaskOverview(taskId);
}
