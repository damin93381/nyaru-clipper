import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { parseTaskLibraryFilters } from "../filters";
import { renderWorkstation } from "../../../testing/renderWorkstation";

const taskTitle = "在很长很长的夏夜里整理主播回放并保留完整的字幕、翻译、模型选择与导出说明，供下一次复核时继续使用".repeat(3);

const listItem = {
  archived_at: null,
  created_at: "2026-07-10T03:00:00Z",
  current_stage: "translation",
  progress_percent: 58,
  source_kind: "bilibili",
  source_label: "夏日档案直播",
  status: "running",
  storage_bytes: 4_096,
  tags: ["夏季", "待复核"],
  task_id: "task-42",
  title: taskTitle,
  updated_at: "2026-07-11T03:00:00Z",
} as const;

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
}

function latestTaskPageRequest(requestedUrls: readonly URL[]): URL | undefined {
  return [...requestedUrls].reverse().find((url) => url.pathname.endsWith("/api/v2/tasks"));
}

async function renderTaskLibrary(route?: string): Promise<void> {
  const { TaskLibraryPage } = await import("../TaskLibraryPage");
  renderWorkstation(<TaskLibraryPage />, { route });
}

describe("TaskLibraryPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.resetModules();
    window.history.pushState({}, "", "/workstation");
  });

  it("falls back from invalid URL filters to the documented defaults", () => {
    const filters = parseTaskLibraryFilters(new URLSearchParams("sort=unknown&direction=sideways&page=0&pageSize=5"));

    expect(filters).toMatchObject({ sort: "updated_at", direction: "desc", page: 1, pageSize: 50 });
  });

  it("loads the library summary and a server-filtered task page", async () => {
    const requestedUrls: URL[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      requestedUrls.push(url);
      if (url.pathname.endsWith("/summary")) {
        return jsonResponse({ active: 1, archived: 2, failed: 3, queued: 4, review_required: 5, storage_bytes: 6_144 });
      }
      if (url.pathname.endsWith("/tasks/task-42")) {
        return jsonResponse({ ...listItem, artifact_readiness: [], artifacts: [], execution_progress: null, pipeline_run_id: null, recovery_actions: [], safe_logs: [], stages: [] });
      }
      return jsonResponse({ items: [listItem], page: 1, page_count: 2, page_size: 50, total: 51 });
    });

    await renderTaskLibrary("/workstation?status=running&source=bilibili&tag=%E5%A4%8F%E5%AD%A3");

    expect(await screen.findByText("运行中 1")).toBeVisible();
    expect(screen.getByText("已归档 2")).toBeVisible();
    expect(screen.getByText("存储 6.0 KB")).toBeVisible();
    expect(taskTitle.length).toBeGreaterThan(120);
    expect(screen.getByTitle(taskTitle)).toBeVisible();
    expect(screen.getByRole("row", { name: new RegExp(taskTitle.slice(0, 24)) })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "标签" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "当前阶段" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "进度" })).toBeVisible();
    expect(screen.getByText("夏季")).toBeVisible();
    expect(screen.getByText("翻译")).toBeVisible();
    expect(screen.getByText("58%")).toBeVisible();
    await waitFor(() => expect(requestedUrls.some((url) => url.pathname.endsWith("/api/v2/tasks"))).toBe(true));
    const taskRequest = requestedUrls.find((url) => url.pathname.endsWith("/api/v2/tasks"));
    expect(taskRequest?.searchParams.getAll("statuses")).toEqual(["running"]);
    expect(taskRequest?.searchParams.get("source_kind")).toBe("bilibili");
    expect(taskRequest?.searchParams.get("tag")).toBe("夏季");
  });

  it("debounces search, persists filters in the URL, and requests the next server page", async () => {
    const requestedUrls: URL[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      requestedUrls.push(url);
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      return jsonResponse({ items: [listItem], page: Number(url.searchParams.get("page") ?? 1), page_count: 2, page_size: 50, total: 51 });
    });

    await renderTaskLibrary();
    await screen.findByRole("row", { name: new RegExp(taskTitle.slice(0, 24)) });
    const search = screen.getByRole("searchbox", { name: "搜索任务" });
    fireEvent.change(search, { target: { value: "夏日" } });
    expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("query")).toBeNull();

    await waitFor(() => expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("query")).toBe("夏日"));
  });

  it("sets and clears the server-side tag filter while preserving URL query semantics", async () => {
    const requestedUrls: URL[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      requestedUrls.push(url);
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      return jsonResponse({ items: [listItem], page: 1, page_count: 1, page_size: 50, total: 1 });
    });

    await renderTaskLibrary("/workstation?tag=%E5%A4%8F%E5%AD%A3");
    const tag = await screen.findByRole("textbox", { name: "标签" });
    expect(tag).toHaveValue("夏季");
    expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("tag")).toBe("夏季");

    fireEvent.click(screen.getByRole("button", { name: "清除标签" }));
    await waitFor(() => expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("tag")).toBeNull());
    expect(tag).toHaveValue("");

    fireEvent.change(tag, { target: { value: "待复核" } });
    fireEvent.click(screen.getByRole("button", { name: "应用标签" }));
    await waitFor(() => expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("tag")).toBe("待复核"));
  });

  it("persists date and readiness filters in the URL and sends them to the server", async () => {
    const requestedUrls: URL[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      requestedUrls.push(url);
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      return jsonResponse({ items: [listItem], page: 1, page_count: 1, page_size: 50, total: 1 });
    });

    await renderTaskLibrary("/workstation?updatedFrom=2026-07-01&updatedTo=2026-07-12&readiness=missing");

    expect(await screen.findByLabelText("更新开始日期")).toHaveValue("2026-07-01");
    expect(screen.getByLabelText("更新结束日期")).toHaveValue("2026-07-12");
    expect(screen.getByLabelText("产物状态")).toHaveValue("missing");
    expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("updated_from")).toBe("2026-07-01T00:00:00.000Z");
    expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("updated_to")).toBe("2026-07-12T23:59:59.999Z");
    expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("readiness")).toBe("missing");

    fireEvent.change(screen.getByLabelText("产物状态"), { target: { value: "failed" } });
    await waitFor(() => expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("readiness")).toBe("failed"));
  });

  it("requests the next page from the server", async () => {
    const requestedUrls: URL[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      requestedUrls.push(url);
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      return jsonResponse({ items: [listItem], page: Number(url.searchParams.get("page") ?? 1), page_count: 2, page_size: 50, total: 51 });
    });

    await renderTaskLibrary();
    const row = await screen.findByRole("row", { name: new RegExp(taskTitle.slice(0, 24)) });
    fireEvent.click(row);
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(latestTaskPageRequest(requestedUrls)?.searchParams.get("page")).toBe("2"));
    expect(await screen.findByRole("row", { name: new RegExp(taskTitle.slice(0, 24)) })).toHaveAttribute("aria-selected", "true");
  });

  it("announces the active sort direction from table headers", async () => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      return jsonResponse({ items: [listItem], page: 1, page_count: 1, page_size: 50, total: 1 });
    });

    await renderTaskLibrary();
    const titleHeader = await screen.findByRole("columnheader", { name: "任务" });
    const updatedHeader = screen.getByRole("columnheader", { name: "更新" });
    expect(titleHeader).not.toHaveAttribute("aria-sort");
    expect(updatedHeader).toHaveAttribute("aria-sort", "descending");

    fireEvent.click(screen.getByRole("button", { name: "任务" }));
    await waitFor(() => expect(titleHeader).toHaveAttribute("aria-sort", "descending"));
    expect(updatedHeader).not.toHaveAttribute("aria-sort");
    fireEvent.click(screen.getByRole("button", { name: "任务" }));
    await waitFor(() => expect(titleHeader).toHaveAttribute("aria-sort", "ascending"));
  });

  it("makes the dense task table's horizontal overflow discoverable and keyboard-operable", async () => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      return jsonResponse({ items: [listItem], page: 1, page_count: 1, page_size: 50, total: 1 });
    });

    await renderTaskLibrary();
    const scrollRegion = await screen.findByRole("region", { name: "任务表格，可水平滚动" });
    const scrollBy = vi.fn();
    Object.assign(scrollRegion, { scrollBy });

    expect(scrollRegion).toHaveAttribute("tabindex", "0");
    expect(scrollRegion).toHaveAccessibleDescription("进度、更新时间和存储位于右侧；可横向滚动查看。聚焦表格后，可使用左右方向键滚动。");
    expect(screen.getByText(/进度、更新时间和存储位于右侧；可横向滚动查看。/)).toBeVisible();

    fireEvent.keyDown(scrollRegion, { key: "ArrowRight" });
    expect(scrollBy).toHaveBeenCalledOnce();
  });

  it("keeps failed bulk rows selected and announces the per-row result", async () => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 1, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      if (url.pathname.endsWith("/bulk")) {
        expect(input instanceof Request ? input.method : init?.method).toBe("POST");
        return jsonResponse({ results: [{ task_id: "task-42", status: "rejected", message: "仍在处理中" }] });
      }
      return jsonResponse({ items: [listItem], page: 1, page_count: 1, page_size: 50, total: 1 });
    });

    await renderTaskLibrary();
    const row = await screen.findByRole("row", { name: new RegExp(taskTitle.slice(0, 24)) });
    fireEvent.click(row);
    fireEvent.click(screen.getByRole("button", { name: "归档选中任务" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认归档" }));

    expect(await screen.findByRole("status")).toHaveTextContent("task-42：仍在处理中");
    expect(row).toHaveAttribute("aria-selected", "true");
  });

  it("confirms bulk tag and requeue requests and reports each requeue result", async () => {
    const bulkBodies: unknown[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 1, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      if (url.pathname.endsWith("/bulk")) {
        const requestBody = input instanceof Request ? await input.clone().json() : JSON.parse(init?.body?.toString() ?? "{}");
        bulkBodies.push(requestBody);
        return jsonResponse({ results: [{ task_id: "task-42", status: "rejected", message: "仍在处理中" }] });
      }
      return jsonResponse({ items: [listItem], page: 1, page_count: 1, page_size: 50, total: 1 });
    });

    await renderTaskLibrary();
    const row = await screen.findByRole("row", { name: new RegExp(taskTitle.slice(0, 24)) });
    fireEvent.click(row);
    fireEvent.click(screen.getByRole("button", { name: "标记选中任务" }));
    expect(await screen.findByText("新标签会替换选中任务的现有标签，并保留未成功任务的选择状态。")).toHaveClass("ny-overlay__description-phrase");
    fireEvent.change(await screen.findByLabelText("批量标签"), { target: { value: "精选，待复核" } });
    fireEvent.click(screen.getByRole("button", { name: "确认标记" }));
    await waitFor(() => expect(bulkBodies).toContainEqual({ operation: "set_tags", task_ids: ["task-42"], tags: ["精选", "待复核"] }));
    expect(await screen.findByRole("status")).toHaveTextContent("task-42：仍在处理中");

    fireEvent.click(screen.getByRole("button", { name: "重新排队选中任务" }));
    expect(await screen.findByText("终止的任务会从中断阶段重新进入队列；")).toHaveClass("ny-overlay__description-phrase");
    expect(screen.getByText("未成功任务会保持选择状态。")).toHaveClass("ny-overlay__description-phrase");
    fireEvent.click(await screen.findByRole("button", { name: "确认重新排队" }));
    await waitFor(() => expect(bulkBodies).toContainEqual({ operation: "requeue", task_ids: ["task-42"] }));
  });

  it("provides recoverable empty and load-failure states", async () => {
    let shouldFail = false;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      if (shouldFail) return new Response("broken", { status: 500 });
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname.endsWith("/summary")) return jsonResponse({ active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 });
      return jsonResponse({ items: [], page: 1, page_count: 0, page_size: 50, total: 0 });
    });

    await renderTaskLibrary();
    expect(await screen.findByText("没有匹配任务")).toBeVisible();
    cleanup();

    shouldFail = true;
    await renderTaskLibrary();
    expect(await screen.findByText("任务库无法读取")).toBeVisible();
    expect(screen.getByRole("button", { name: "重新读取任务库" })).toBeEnabled();
  });
});
