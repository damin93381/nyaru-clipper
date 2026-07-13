import { afterEach, describe, expect, it, vi } from "vitest";

import { workstationKeys } from "../queryKeys";

describe("workstationClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("sends task-list filters through generated query parameters", async () => {
    const requestedUrls: URL[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      requestedUrls.push(new URL(input instanceof Request ? input.url : input.toString()));
      return new Response(JSON.stringify({ items: [], page: 2, page_count: 1, page_size: 50, total: 0 }), {
        headers: { "Content-Type": "application/json" },
      });
    });

    const { workstationClient } = await import("../client");

    const { data, error } = await workstationClient.GET("/api/v2/tasks", {
      params: {
        query: { page: 2, page_size: 50, statuses: ["running"] },
      },
    });

    expect(error).toBeUndefined();
    expect(data?.page).toBe(2);
    const requestedUrl = requestedUrls[0];
    expect(requestedUrl?.searchParams.get("page")).toBe("2");
    expect(requestedUrl?.searchParams.get("page_size")).toBe("50");
    expect(requestedUrl?.searchParams.getAll("statuses")).toEqual(["running"]);
  });

  it("builds stable query keys for workstation task views", () => {
    expect(workstationKeys.all).toEqual(["workstation"]);
    expect(workstationKeys.summary).toEqual(["workstation", "tasks", "summary"]);
    expect(workstationKeys.list({ page: 2, statuses: ["running"] })).toEqual([
      "workstation",
      "tasks",
      "list",
      { page: 2, statuses: ["running"] },
    ]);
    expect(workstationKeys.detail("task-1")).toEqual(["workstation", "tasks", "detail", "task-1"]);
    expect(workstationKeys.queue).toEqual(["workstation", "queue"]);
  });
});
