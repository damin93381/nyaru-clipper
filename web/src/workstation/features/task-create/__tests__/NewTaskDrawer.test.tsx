import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { workstationKeys } from "../../../api/queryKeys";
import { NewTaskDrawer } from "../NewTaskDrawer";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" }, status });
}

function CurrentLocation(): ReactNode {
  return <output aria-label="当前位置">{useLocation().pathname}</output>;
}

function renderDrawer(): QueryClient {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/workstation"]}>
        <NewTaskDrawer open onOpenChange={() => undefined} />
        <CurrentLocation />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

async function request(input: RequestInfo | URL, init?: RequestInit): Promise<{ readonly body: unknown; readonly method: string; readonly url: URL }> {
  if (input instanceof Request) {
    return { body: input.method === "GET" ? undefined : await input.clone().json(), method: input.method, url: new URL(input.url) };
  }
  return { body: init?.body == null ? undefined : JSON.parse(init.body.toString()), method: init?.method ?? "GET", url: new URL(input.toString()) };
}

describe("NewTaskDrawer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("inspects a Bilibili source, retains profile and priority choices, then invalidates workstation cache and navigates", async () => {
    // Given: a v2 API boundary that returns inspected metadata, the sole profile, and a created task.
    const requests: { readonly body: unknown; readonly method: string; readonly url: URL }[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const next = await request(input, init);
      requests.push(next);
      if (next.url.pathname === "/api/v2/sources/bilibili/inspect") return response({ normalized_url: "https://www.bilibili.com/video/BV1drawertest", source_video_id: "BV1drawertest", title: "夏日档案直播", uploader: "Nyaru", duration_seconds: 128 });
      if (next.url.pathname === "/api/v2/processing-profiles") return response({ profiles: [{ id: "standard", name: "Standard", stages: ["ingest", "media_prep"] }] });
      if (next.url.pathname === "/api/v2/tasks") return response({ task_id: "task-created", profile_id: "standard", priority: 7, status: "pending" }, 201);
      return response({ roots: [], root_id: null, relative_path: "", entries: [] });
    });
    const queryClient = renderDrawer();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    // When: the operator selects Bilibili, corrects an invalid URL, inspects it, and submits scheduling options.
    fireEvent.click(screen.getByRole("button", { name: "Bilibili 录播" }));
    const sourceInput = screen.getByRole("textbox", { name: "Bilibili 链接" });
    fireEvent.change(sourceInput, { target: { value: "not-a-url" } });
    fireEvent.click(screen.getByRole("button", { name: "检查来源" }));
    expect(await screen.findByText("请输入有效的 Bilibili 链接。")).toBeVisible();
    fireEvent.change(sourceInput, { target: { value: "https://www.bilibili.com/video/BV1drawertest" } });
    fireEvent.click(screen.getByRole("button", { name: "检查来源" }));
    expect(await screen.findByText("夏日档案直播")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "继续设置" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "优先级" }), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "创建任务" }));

    // Then: the exact inspected URL and options create one task, shared views refresh, and the task workspace opens.
    await waitFor(() => expect(screen.getByLabelText("当前位置")).toHaveTextContent("/workstation/tasks/task-created"));
    expect(requests.find((item) => item.url.pathname === "/api/v2/tasks")).toMatchObject({
      body: { source: { kind: "bilibili", url: "https://www.bilibili.com/video/BV1drawertest" }, profile_id: "standard", priority: 7 },
      method: "POST",
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: workstationKeys.summary });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: workstationKeys.queue });
  });

  it("navigates only through the safe local catalog and submits the selected task-copy mode", async () => {
    // Given: a catalog whose root and descendants are opaque IDs and relative paths.
    const requests: { readonly body: unknown; readonly method: string; readonly url: URL }[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const next = await request(input, init);
      requests.push(next);
      if (next.url.pathname === "/api/v2/sources/local" && next.url.searchParams.get("root_id") === null) return response({ roots: [{ id: "root-media", name: "媒体导入" }], root_id: null, relative_path: "", entries: [] });
      if (next.url.pathname === "/api/v2/sources/local") return response({ roots: [{ id: "root-media", name: "媒体导入" }], root_id: "root-media", relative_path: "vod", entries: [{ name: "summer.mp4", relative_path: "vod/summer.mp4", kind: "file" }, { name: "archive", relative_path: "vod/archive", kind: "directory" }] });
      if (next.url.pathname === "/api/v2/processing-profiles") return response({ profiles: [{ id: "standard", name: "Standard", stages: ["ingest"] }] });
      if (next.url.pathname === "/api/v2/tasks") return response({ task_id: "task-copy", profile_id: "standard", priority: 0, status: "pending" }, 201);
      return response({ detail: "unexpected request" }, 500);
    });
    renderDrawer();

    // When: the operator opens a trusted root, selects a visible file, and chooses a task-owned copy.
    fireEvent.click(screen.getByRole("button", { name: "本地文件" }));
    fireEvent.click(await screen.findByRole("button", { name: "媒体导入" }));
    expect(await screen.findByRole("button", { name: "summer.mp4" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "summer.mp4" }));
    fireEvent.click(screen.getByRole("radio", { name: "复制到任务存储" }));
    fireEvent.click(screen.getByRole("button", { name: "继续设置" }));
    fireEvent.click(screen.getByRole("button", { name: "创建任务" }));

    // Then: no host path enters the UI or payload; the v2 request explicitly asks for a copy.
    await waitFor(() => expect(screen.getByLabelText("当前位置")).toHaveTextContent("/workstation/tasks/task-copy"));
    expect(requests.find((item) => item.url.pathname === "/api/v2/tasks")).toMatchObject({
      body: { source: { kind: "local", root_id: "root-media", relative_path: "vod/summer.mp4", import_mode: "copy" }, profile_id: "standard", priority: 0 },
    });
    expect(screen.queryByText(/\/tmp|trusted-media/)).not.toBeInTheDocument();
  });

  it("maps server fields without clearing dirty form values and confirms before abandoning them", async () => {
    // Given: a server that rejects the selected priority at the v2 boundary.
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const next = await request(input, init);
      if (next.url.pathname === "/api/v2/sources/bilibili/inspect") return response({ normalized_url: "https://www.bilibili.com/video/BV1failure", source_video_id: "BV1failure", title: "失败后保留", uploader: null, duration_seconds: null });
      if (next.url.pathname === "/api/v2/processing-profiles") return response({ profiles: [{ id: "standard", name: "Standard", stages: ["ingest"] }] });
      if (next.url.pathname === "/api/v2/tasks") return response({ detail: [{ loc: ["body", "priority"], msg: "优先级超出允许范围" }] }, 422);
      return response({ roots: [], root_id: null, relative_path: "", entries: [] });
    });
    renderDrawer();

    // When: creation fails after a complete inspected Bilibili draft, then the operator attempts to close it.
    fireEvent.click(screen.getByRole("button", { name: "Bilibili 录播" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Bilibili 链接" }), { target: { value: "https://www.bilibili.com/video/BV1failure" } });
    fireEvent.click(screen.getByRole("button", { name: "检查来源" }));
    fireEvent.click(await screen.findByRole("button", { name: "继续设置" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "优先级" }), { target: { value: "99" } });
    fireEvent.click(screen.getByRole("button", { name: "创建任务" }));

    // Then: the field-level message is visible, the entered value remains, and close asks for a deliberate discard.
    expect(await screen.findByText("优先级超出允许范围")).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "优先级" })).toHaveValue(99);
    fireEvent.click(screen.getByRole("button", { name: "关闭新建任务" }));
    expect(await screen.findByRole("alertdialog", { name: "放弃未保存的任务设置？" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByRole("spinbutton", { name: "优先级" })).toHaveValue(99);
  });
});
