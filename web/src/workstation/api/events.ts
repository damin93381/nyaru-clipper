const defaultApiOrigin = "http://127.0.0.1:8000";

export const workstationEventNames = [
  "task.created",
  "task.updated",
  "stage.updated",
  "artifact.ready",
  "queue.updated",
  "runtime.warning",
] as const;

export type WorkstationEventName = (typeof workstationEventNames)[number];

export const workstationReconnectDelays = [1_000, 2_000, 5_000, 10_000, 30_000] as const;
export const workstationFallbackPollingInterval = 15_000;

export function getWorkstationEventsUrl(): string {
  const apiOrigin = (import.meta.env.VITE_API_BASE_URL ?? defaultApiOrigin)
    .replace(/\/+$/, "")
    .replace(/\/api$/, "");

  return new URL("/api/v2/events", apiOrigin).toString();
}
