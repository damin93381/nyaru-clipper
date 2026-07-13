import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContextInspector } from "../ContextInspector";
import { renderWorkstation } from "../../testing/renderWorkstation";

const activeTaskTitle = "高光候选片段";
const queueSnapshot = {
  active: { position: 0, priority: 0, state: "running", task_id: "task-active" },
  paused: [],
  queued: [{ position: 1, priority: 0, state: "queued", task_id: "task-second" }],
  revision: 7,
} as const;

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
}

describe("ContextInspector", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/workstation");
  });

  it("protects the default workspace clause as one CJK semantic phrase", () => {
    vi.stubGlobal("fetch", async () => jsonResponse({ active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 }));

    renderWorkstation(<ContextInspector />);

    const phrase = screen.getByText("当前工作区").parentElement;
    expect(phrase).toHaveClass("ny-workstation__inspector-copy-phrase");
    expect(phrase).toHaveTextContent("即可在不离开当前工作区的情况下");
  });

  it("ellipsizes an active GPU task title while retaining its complete tooltip", async () => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 1, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      return jsonResponse({
        items: [{
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
          title: activeTaskTitle,
          updated_at: "2026-07-11T03:00:00Z",
        }],
        page: 1,
        page_count: 1,
        page_size: 1,
        total: 1,
      });
    });

    renderWorkstation(<ContextInspector />);

    const title = await screen.findByTitle(activeTaskTitle);
    expect(title).toHaveClass("ny-workstation__inspector-task-title");
    expect(title).toHaveTextContent(activeTaskTitle);
  });

  it("shows a selected queue item in the persistent context rail", async () => {
    vi.stubGlobal("fetch", async () => jsonResponse(queueSnapshot));

    renderWorkstation(<ContextInspector />, { route: "/workstation/queue?selected=task-second" });

    expect(await screen.findByRole("heading", { name: "已选队列项" })).toBeVisible();
    expect(screen.getByText("task-second")).toBeVisible();
    expect(screen.getByLabelText("上下文检查器")).toContainElement(screen.getByText("队列检查器"));
  });
});
