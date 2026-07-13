import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { useWorkstationEvents } from "../useWorkstationEvents";

class EventSourceHarness {
  static instances: EventSourceHarness[] = [];

  readonly listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;

  constructor(readonly url: string) {
    EventSourceHarness.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close(): void {}

  emit(type: string, data: object, lastEventId = ""): void {
    const event = new MessageEvent(type, { data: JSON.stringify(data), lastEventId });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function EventConnectionProbe(): ReactNode {
  useWorkstationEvents();
  return null;
}

describe("useWorkstationEvents", () => {
  afterEach(() => {
    EventSourceHarness.instances = [];
    vi.unstubAllGlobals();
  });

  it("invalidates task projections when another tab deletes a task", () => {
    vi.stubGlobal("EventSource", EventSourceHarness);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

    render(<QueryClientProvider client={queryClient}><EventConnectionProbe /></QueryClientProvider>);
    const source = EventSourceHarness.instances[0];
    expect(source).toBeDefined();

    act(() => source?.emit("task.deleted", { task_id: "task-deleted" }, "23"));

    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workstation", "tasks", "summary"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workstation", "tasks", "list"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workstation", "tasks", "detail", "task-deleted"] });
  });
});
