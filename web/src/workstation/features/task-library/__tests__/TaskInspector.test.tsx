import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWorkstation } from "../../../testing/renderWorkstation";

const longTitle = "在很长很长的夏夜里整理主播回放并保留完整的字幕、翻译、模型选择与导出说明，供下一次复核时继续使用".repeat(3);
const task = {
  archived_at: null,
  artifact_readiness: [],
  artifacts: [],
  created_at: "2026-07-10T03:00:00Z",
  current_stage: "translation",
  execution_progress: null,
  pipeline_run_id: null,
  progress_percent: 58,
  recovery_actions: [],
  safe_logs: [],
  source_kind: "bilibili",
  source_label: "夏日档案直播",
  stages: [],
  status: "running",
  storage_bytes: 4_096,
  tags: ["夏季", "待复核"],
  task_id: "task-42",
  title: longTitle,
  updated_at: "2026-07-11T03:00:00Z",
} as const;

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
}

describe("TaskInspector", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("patches only changed tags when the stored title exceeds the title limit", async () => {
    const patchBodies: unknown[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : undefined;
      const url = new URL(request?.url ?? input.toString());
      const method = request?.method ?? init?.method ?? "GET";
      if (method === "PATCH") {
        patchBodies.push(JSON.parse(request ? await request.text() : String(init?.body)));
        return jsonResponse(task);
      }
      return jsonResponse(task);
    });

    const { TaskInspector } = await import("../TaskInspector");
    renderWorkstation(<TaskInspector taskId="task-42" />);

    expect((await screen.findByLabelText("任务标题") as HTMLInputElement).value.length).toBeGreaterThan(120);
    expect(screen.getByRole("heading", { level: 2 })).toHaveClass("ny-task-inspector__heading");
    expect(screen.getByRole("heading", { level: 2 })).toHaveAttribute("title", longTitle);
    fireEvent.change(screen.getByLabelText("标签（用中文逗号分隔）"), { target: { value: "夏季，新标签" } });
    fireEvent.click(screen.getByRole("button", { name: "保存元数据" }));

    expect(await screen.findByText("已保存任务元数据。")).toBeVisible();
    expect(patchBodies).toEqual([{ tags: ["夏季", "新标签"] }]);
  });
});
