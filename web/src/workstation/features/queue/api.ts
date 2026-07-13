import type { components } from "../../../generated/api-schema";

import { workstationClient } from "../../api/client";

export type QueueItem = components["schemas"]["QueueItemResponse"];
export type QueueSnapshot = components["schemas"]["QueueSnapshotResponse"];
export type QueueState = components["schemas"]["QueueStateRequest"]["state"];

export class QueueApiError extends Error {
  constructor(readonly action: string) {
    super(action);
    this.name = "QueueApiError";
  }
}

export class QueueConflictError extends QueueApiError {
  constructor(readonly snapshot: QueueSnapshot) {
    super("队列顺序已变更");
    this.name = "QueueConflictError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isQueueItem(value: unknown): value is QueueItem {
  return isRecord(value)
    && typeof value.task_id === "string"
    && typeof value.position === "number"
    && typeof value.priority === "number"
    && typeof value.state === "string";
}

function isQueueSnapshot(value: unknown): value is QueueSnapshot {
  return isRecord(value)
    && typeof value.revision === "number"
    && (value.active === null || isQueueItem(value.active))
    && Array.isArray(value.queued)
    && value.queued.every(isQueueItem)
    && Array.isArray(value.paused)
    && value.paused.every(isQueueItem);
}

async function requireQueueSnapshot(
  request: Promise<{ readonly data?: QueueSnapshot; readonly error?: unknown; readonly response: Response }>,
  action: string,
): Promise<QueueSnapshot> {
  const { data, error, response } = await request;
  if (data !== undefined) return data;
  if (response.status === 409) {
    if (isQueueSnapshot(error)) throw new QueueConflictError(error);
  }
  throw new QueueApiError(action);
}

export function getQueue(): Promise<QueueSnapshot> {
  return requireQueueSnapshot(workstationClient.GET("/api/v2/queue", { parseAs: "json" }), "处理队列无法读取");
}

export function reorderQueue(orderedTaskIds: readonly string[], expectedRevision: number): Promise<QueueSnapshot> {
  return requireQueueSnapshot(
    workstationClient.PUT("/api/v2/queue/order", { body: { expected_revision: expectedRevision, ordered_task_ids: [...orderedTaskIds] }, parseAs: "json" }),
    "队列排序没有保存",
  );
}

export function setQueueItemState(taskId: string, state: QueueState): Promise<QueueSnapshot> {
  return requireQueueSnapshot(
    workstationClient.PATCH("/api/v2/queue/{task_id}", { body: { state }, params: { path: { task_id: taskId } }, parseAs: "json" }),
    "队列状态没有保存",
  );
}

export function reorderSnapshot(snapshot: QueueSnapshot, orderedTaskIds: readonly string[]): QueueSnapshot {
  const itemsByTaskId = new Map(snapshot.queued.map((item) => [item.task_id, item]));
  return {
    ...snapshot,
    queued: orderedTaskIds.flatMap((taskId, index) => {
      const item = itemsByTaskId.get(taskId);
      return item === undefined ? [] : [{ ...item, position: index + 1 }];
    }),
  };
}
