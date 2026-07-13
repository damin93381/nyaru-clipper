import type { components } from "../../../generated/api-schema";
import type { TaskLibraryFilters } from "./filters";

import { workstationClient } from "../../api/client";
import { toTaskListQuery } from "./filters";

export type TaskListItem = components["schemas"]["TaskListItem"];
export type TaskLibrarySummary = components["schemas"]["TaskLibrarySummary"];
export type TaskOverview = components["schemas"]["TaskOverview"];
export type BulkTaskMutationOperation = "archive" | "unarchive" | "delete";
export type BulkTaskMutationResponse = components["schemas"]["BulkTaskMutationResponse"];

export class TaskLibraryApiError extends Error {
  constructor(readonly action: string) {
    super(action);
    this.name = "TaskLibraryApiError";
  }
}

async function requireData<Result>(request: Promise<{ readonly data?: Result; readonly error?: unknown }>, action: string): Promise<Result> {
  const { data } = await request;
  if (data === undefined) throw new TaskLibraryApiError(action);
  return data;
}

export function getTaskLibrarySummary(): Promise<TaskLibrarySummary> {
  return requireData(workstationClient.GET("/api/v2/tasks/summary"), "任务库摘要无法读取");
}

export function getTaskLibraryPage(filters: TaskLibraryFilters): Promise<components["schemas"]["TaskListPage"]> {
  return requireData(
    workstationClient.GET("/api/v2/tasks", { params: { query: toTaskListQuery(filters) } }),
    "任务库无法读取",
  );
}

export function getTaskOverview(taskId: string): Promise<TaskOverview> {
  return requireData(workstationClient.GET("/api/v2/tasks/{task_id}", { params: { path: { task_id: taskId } } }), "任务详情无法读取");
}

export function updateTaskMetadata(taskId: string, metadata: components["schemas"]["TaskPatchRequest"]): Promise<TaskOverview> {
  return requireData(
    workstationClient.PATCH("/api/v2/tasks/{task_id}", { params: { path: { task_id: taskId } }, body: metadata }),
    "任务元数据无法保存",
  );
}

export function mutateTasks(operation: BulkTaskMutationOperation, taskIds: readonly string[]): Promise<BulkTaskMutationResponse> {
  return requireData(workstationClient.POST("/api/v2/tasks/bulk", { body: { operation, task_ids: [...taskIds] } }), "批量任务操作失败");
}
