import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRouter } from "../../router";
import { WorkstationApp } from "../WorkstationApp";
import { renderWorkstation } from "../testing/renderWorkstation";

class EventSourceHarness {
  static instances: EventSourceHarness[] = [];

  readonly listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;

  constructor(readonly url: string) {
    EventSourceHarness.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.readyState = 2;
  }

  emitOpen() {
    this.readyState = 1;
    this.onopen?.();
  }

  emitError() {
    this.onerror?.();
  }

  emit(type: string, data: object, lastEventId = "") {
    const event = new MessageEvent(type, { data: JSON.stringify(data), lastEventId });
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}

function latestEventSource(): EventSourceHarness | undefined {
  return EventSourceHarness.instances[EventSourceHarness.instances.length - 1];
}

describe("WorkstationApp", () => {
  afterEach(() => {
    EventSourceHarness.instances = [];
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("renders only implemented workstation navigation", () => {
    vi.stubGlobal("EventSource", EventSourceHarness);

    renderWorkstation(<WorkstationApp />);

    expect(screen.getByRole("link", { name: "任务库" })).toHaveAttribute("href", "/workstation");
    expect(screen.getByRole("link", { name: "处理队列" })).toHaveAttribute("href", "/workstation/queue");
    expect(screen.queryByRole("link", { name: "成片导出" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "存储管理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "运行环境" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "设置" })).not.toBeInTheDocument();
  });

  it("mounts the workstation route through the application router", () => {
    vi.stubGlobal("EventSource", EventSourceHarness);
    window.history.pushState({}, "", "/workstation");
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <AppRouter />
      </QueryClientProvider>,
    );

    expect(screen.getByRole("heading", { name: "任务库" })).toBeInTheDocument();
  });

  it("invalidates the task projections affected by task and queue events", () => {
    vi.stubGlobal("EventSource", EventSourceHarness);
    const queryClient = renderWorkstation(<WorkstationApp />);
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

    const source = EventSourceHarness.instances[0];
    expect(source).toBeDefined();
    act(() => {
      source?.emit("task.updated", { task_id: "task-42", status: "running" }, "7");
      source?.emit("queue.updated", { revision: 2 }, "8");
    });

    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workstation", "tasks", "summary"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workstation", "tasks", "list"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workstation", "tasks", "detail", "task-42"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workstation", "queue"] });
  });

  it("resumes a manual EventSource replacement after the last durable event without a duplicate cursor", () => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", EventSourceHarness);
    renderWorkstation(<WorkstationApp />);

    const firstSource = latestEventSource();
    act(() => {
      firstSource?.emit("task.updated", { task_id: "task-42", status: "running" }, "17");
      firstSource?.emitError();
      vi.advanceTimersByTime(1_000);
    });

    const replacementSource = latestEventSource();

    expect(replacementSource).not.toBe(firstSource);
    expect(new URL(replacementSource?.url ?? "http://example.test").searchParams.get("cursor")).toBe("17");
  });

  it("activates polling after five connection failures without clearing cached task data", () => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", EventSourceHarness);
    const queryClient = renderWorkstation(<WorkstationApp />, {
      seed: [["workstation", "tasks", "detail", "task-42"]],
    });
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

    for (const delaySeconds of [1, 2, 5, 10, 30]) {
      act(() => {
        latestEventSource()?.emitError();
        vi.advanceTimersByTime(delaySeconds * 1_000);
      });
    }

    expect(screen.getByRole("status")).toHaveTextContent("实时连接不可用");
    expect(queryClient.getQueryData(["workstation", "tasks", "detail", "task-42"])).toEqual({ cached: true });

    act(() => vi.advanceTimersByTime(15_000));
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workstation", "tasks"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workstation", "queue"] });
    expect(queryClient.getQueryData(["workstation", "tasks", "detail", "task-42"])).toEqual({ cached: true });
  });

  it("stops fallback polling when the next stream opens", () => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", EventSourceHarness);
    const queryClient = renderWorkstation(<WorkstationApp />);
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

    for (const delaySeconds of [1, 2, 5, 10, 30]) {
      act(() => {
        latestEventSource()?.emitError();
        vi.advanceTimersByTime(delaySeconds * 1_000);
      });
    }
    act(() => latestEventSource()?.emitOpen());
    invalidateQueries.mockClear();

    act(() => vi.advanceTimersByTime(15_000));

    expect(screen.getByRole("status")).toHaveTextContent("实时连接已恢复");
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it("keeps workstation links keyboard reachable", () => {
    vi.stubGlobal("EventSource", EventSourceHarness);
    renderWorkstation(<WorkstationApp />);

    const queueLink = screen.getByRole("link", { name: "处理队列" });
    queueLink.focus();
    fireEvent.keyDown(queueLink, { key: "Enter" });

    expect(queueLink).toHaveFocus();
  });

  it("keeps the task reference together in the CJK inspector copy", () => {
    vi.stubGlobal("EventSource", EventSourceHarness);
    renderWorkstation(<WorkstationApp />, { route: "/tasks/task-42" });

    expect(screen.getByText("任务 task-42")).toHaveClass("ny-workstation__inspector-task-reference");
  });

  it("keeps semantic CJK inspector phrases together", () => {
    vi.stubGlobal("EventSource", EventSourceHarness);
    renderWorkstation(<WorkstationApp />);

    expect(screen.getByText("当前工作区")).toHaveClass("ny-workstation__inspector-copy-phrase");
    expect(screen.getByText("的情况下")).toHaveClass("ny-workstation__inspector-copy-phrase");
  });

  it("keeps the selected-task result phrase together", () => {
    vi.stubGlobal("EventSource", EventSourceHarness);
    renderWorkstation(<WorkstationApp />, { route: "/tasks/task-42" });

    expect(screen.getByText("此处显示")).toHaveClass("ny-workstation__inspector-copy-phrase");
  });
});
