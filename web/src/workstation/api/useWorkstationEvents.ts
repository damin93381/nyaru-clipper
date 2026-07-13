import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getWorkstationEventsUrl, workstationEventNames, workstationFallbackPollingInterval, workstationReconnectDelays } from "./events";
import { workstationKeys } from "./queryKeys";

export type WorkstationConnectionState = "connecting" | "open" | "fallback";

export interface WorkstationEventConnection {
  readonly state: WorkstationConnectionState;
  readonly lastEventId: string | null;
}

interface EventPayload {
  readonly task_id?: string;
}

function hasTaskId(value: unknown): value is { readonly task_id: string } {
  return value !== null && typeof value === "object" && "task_id" in value && typeof value.task_id === "string";
}

function parseEventPayload(data: string): EventPayload {
  try {
    const parsed: unknown = JSON.parse(data);
    if (hasTaskId(parsed)) {
      return { task_id: parsed.task_id };
    }
  } catch {
    return {};
  }

  return {};
}

function isTaskProjectionEvent(eventName: string): boolean {
  return eventName === "task.created" || eventName === "task.deleted" || eventName === "task.updated" || eventName === "stage.updated" || eventName === "artifact.ready";
}

export function useWorkstationEvents(): WorkstationEventConnection {
  const queryClient = useQueryClient();
  const [state, setState] = useState<WorkstationConnectionState>("connecting");
  const [lastEventId, setLastEventId] = useState<string | null>(null);

  useEffect(() => {
    let eventSource: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let fallbackTimer: ReturnType<typeof setInterval> | null = null;
    let consecutiveFailures = 0;
    let lastReceivedEventId: string | null = null;
    let disposed = false;

    const invalidateTaskProjections = (taskId: string | undefined) => {
      void queryClient.invalidateQueries({ queryKey: workstationKeys.summary });
      void queryClient.invalidateQueries({ queryKey: ["workstation", "tasks", "list"] });
      if (taskId !== undefined) {
        void queryClient.invalidateQueries({ queryKey: workstationKeys.detail(taskId) });
      }
    };

    const invalidateFallbackProjections = () => {
      void queryClient.invalidateQueries({ queryKey: ["workstation", "tasks"] });
      void queryClient.invalidateQueries({ queryKey: workstationKeys.queue });
    };

    const stopFallbackPolling = () => {
      if (fallbackTimer !== null) {
        clearInterval(fallbackTimer);
        fallbackTimer = null;
      }
    };

    const startFallbackPolling = () => {
      if (fallbackTimer === null) {
        fallbackTimer = setInterval(invalidateFallbackProjections, workstationFallbackPollingInterval);
      }
    };

    const connect = () => {
      if (disposed) {
        return;
      }

      setState(consecutiveFailures >= workstationReconnectDelays.length ? "fallback" : "connecting");
      eventSource = new EventSource(getWorkstationEventsUrl(lastReceivedEventId));
      eventSource.onopen = () => {
        if (disposed) {
          return;
        }
        consecutiveFailures = 0;
        stopFallbackPolling();
        setState("open");
      };
      eventSource.onerror = () => {
        if (disposed) {
          return;
        }

        eventSource?.close();
        consecutiveFailures += 1;
        const delayIndex = Math.min(consecutiveFailures - 1, workstationReconnectDelays.length - 1);
        const retryDelay = workstationReconnectDelays[delayIndex];

        if (consecutiveFailures >= workstationReconnectDelays.length) {
          setState("fallback");
          startFallbackPolling();
        } else {
          setState("connecting");
        }

        reconnectTimer = setTimeout(connect, retryDelay);
      };

      for (const eventName of workstationEventNames) {
        eventSource.addEventListener(eventName, (event) => {
          if (!(event instanceof MessageEvent) || typeof event.data !== "string") {
            return;
          }
          if (event.lastEventId !== "") {
            lastReceivedEventId = event.lastEventId;
            setLastEventId(event.lastEventId);
          }
          if (isTaskProjectionEvent(eventName)) {
            invalidateTaskProjections(parseEventPayload(event.data).task_id);
            return;
          }
          if (eventName === "queue.updated") {
            void queryClient.invalidateQueries({ queryKey: workstationKeys.queue });
          }
        });
      }
    };

    connect();

    return () => {
      disposed = true;
      eventSource?.close();
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
      }
      stopFallbackPolling();
    };
  }, [queryClient]);

  return { state, lastEventId };
}
