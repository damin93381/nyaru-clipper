import type { operations } from "../../generated/api-schema";

export type WorkstationTaskListFilters = NonNullable<
  operations["list_task_library_endpoint_api_v2_tasks_get"]["parameters"]["query"]
>;

export const workstationKeys = {
  all: ["workstation"] as const,
  summary: ["workstation", "tasks", "summary"] as const,
  list: (filters: WorkstationTaskListFilters) => ["workstation", "tasks", "list", filters] as const,
  detail: (taskId: string) => ["workstation", "tasks", "detail", taskId] as const,
  queue: ["workstation", "queue"] as const,
} as const;
