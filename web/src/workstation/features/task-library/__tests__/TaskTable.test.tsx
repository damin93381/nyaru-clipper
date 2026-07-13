import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TaskListItem } from "../api";
import { TaskTable } from "../TaskTable";
import { renderWorkstation } from "../../../testing/renderWorkstation";

const item = {
  archived_at: null,
  created_at: "2026-07-10T03:00:00Z",
  current_stage: "highlight",
  progress_percent: 58,
  source_kind: "bilibili",
  source_label: "夏日档案直播",
  status: "running",
  storage_bytes: 4_096,
  tags: [],
  task_id: "task-42",
  title: "高光候选片段",
  updated_at: "2026-07-11T03:00:00Z",
} satisfies TaskListItem;

function renderTaskTable(): void {
  renderWorkstation(
    <TaskTable
      filters={{ direction: "desc", page: 1, pageSize: 50, query: "", readiness: null, sort: "updated_at", sourceKind: "all", statuses: [], tag: null, updatedFrom: null, updatedTo: null }}
      inspectedTaskId={null}
      items={[item]}
      onInspect={vi.fn()}
      onOpenTask={vi.fn()}
      onSelectionChange={vi.fn()}
      onSort={vi.fn()}
      selectedTaskIds={new Set()}
    />,
  );
}

function prepareScrollRegion(): { readonly scrollBy: ReturnType<typeof vi.fn>; readonly scrollRegion: HTMLElement } {
  const scrollRegion = screen.getByRole("region", { name: "任务表格，可水平滚动" });
  const scrollBy = vi.fn();
  Object.assign(scrollRegion, { scrollBy });
  Object.defineProperty(scrollRegion, "clientWidth", { configurable: true, value: 480 });
  return { scrollBy, scrollRegion };
}

describe("TaskTable", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("smoothly scrolls one viewport for each keyboard direction by default", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
    renderTaskTable();
    const { scrollBy, scrollRegion } = prepareScrollRegion();

    fireEvent.keyDown(scrollRegion, { key: "ArrowRight" });
    expect(scrollBy).toHaveBeenCalledWith({ behavior: "smooth", left: 480 });
    fireEvent.keyDown(scrollRegion, { key: "ArrowLeft" });
    expect(scrollBy).toHaveBeenLastCalledWith({ behavior: "smooth", left: -480 });
  });

  it("uses instant keyboard scrolling when reduced motion is requested", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
    renderTaskTable();
    const { scrollBy, scrollRegion } = prepareScrollRegion();

    fireEvent.keyDown(scrollRegion, { key: "ArrowRight" });
    expect(scrollBy).toHaveBeenCalledWith({ behavior: "auto", left: 480 });
  });
});
