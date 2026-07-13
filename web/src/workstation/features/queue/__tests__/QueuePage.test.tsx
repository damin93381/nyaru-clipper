import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWorkstation } from "../../../testing/renderWorkstation";

const queueSnapshot = {
  active: { position: 0, priority: 0, state: "running", task_id: "task-active" },
  paused: [{ position: 4, priority: 0, state: "paused", task_id: "task-paused" }],
  queued: [
    { position: 1, priority: 0, state: "queued", task_id: "task-first" },
    { position: 2, priority: 0, state: "queued", task_id: "task-second" },
    { position: 3, priority: 0, state: "queued", task_id: "task-third" },
  ],
  revision: 7,
} as const;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" }, status });
}

function deferredResponse(): { readonly promise: Promise<Response>; readonly resolve: (response: Response) => void } {
  let resolve: ((response: Response) => void) | undefined;
  const promise = new Promise<Response>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return {
    promise,
    resolve: (response) => resolve?.(response),
  };
}

async function renderQueue(): Promise<void> {
  const { QueuePage } = await import("../QueuePage");
  renderWorkstation(<QueuePage />);
}

function openQueueMenu(taskId: string): void {
  const trigger = screen.getByRole("button", { name: `${taskId} 操作` });
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
}

function queueRowRectangle(top: number): DOMRect {
  return {
    bottom: top + 40,
    height: 40,
    left: 0,
    right: 800,
    toJSON: () => ({}),
    top,
    width: 800,
    x: 0,
    y: top,
  } satisfies DOMRect;
}

function installQueueRowLayout(): void {
  const topByTaskId = new Map([
    ["task-first", 0],
    ["task-second", 48],
    ["task-third", 96],
  ]);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function getBoundingClientRect(this: HTMLElement): DOMRect {
    const dragHandle = this.closest("tr")?.querySelector<HTMLButtonElement>("button[aria-label^='拖动 ']");
    const taskId = dragHandle?.getAttribute("aria-label")?.replace("拖动 ", "");
    const top = taskId === undefined ? undefined : topByTaskId.get(taskId);
    return queueRowRectangle(top ?? -48);
  });
}

async function queueRequest(input: RequestInfo | URL, init?: RequestInit): Promise<{ readonly body: unknown; readonly method: string; readonly url: URL }> {
  if (input instanceof Request) {
    return {
      body: input.method === "GET" ? undefined : await input.clone().json(),
      method: input.method,
      url: new URL(input.url),
    };
  }
  return {
    body: init?.body == null ? undefined : JSON.parse(init.body.toString()),
    method: init?.method ?? "GET",
    url: new URL(input.toString()),
  };
}

describe("QueuePage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("optimistically reorders queued work and sends the current revision", async () => {
    const response = deferredResponse();
    const requests: { body: unknown; method: string; url: URL }[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = await queueRequest(input, init);
      requests.push(request);
      if (request.url.pathname.endsWith("/order")) return response.promise;
      return jsonResponse(queueSnapshot);
    });

    await renderQueue();
    await screen.findByRole("button", { name: "task-first 操作" });
    openQueueMenu("task-first");
    fireEvent.click(await screen.findByRole("menuitem", { name: "下移" }));

    await waitFor(() => expect(requests.some((request) => request.url.pathname.endsWith("/order"))).toBe(true));
    expect(screen.getAllByRole("row").map((row) => row.textContent)).toEqual(expect.arrayContaining([expect.stringMatching(/task-second/), expect.stringMatching(/task-first/)]));
    const reorderRequest = requests.find((request) => request.url.pathname.endsWith("/order"));
    expect(reorderRequest).toMatchObject({ body: { expected_revision: 7, ordered_task_ids: ["task-second", "task-first", "task-third"] }, method: "PUT" });

    response.resolve(jsonResponse({ ...queueSnapshot, queued: [queueSnapshot.queued[1], queueSnapshot.queued[0], queueSnapshot.queued[2]], revision: 8 }));
    await waitFor(() => expect(screen.getByText("队列版本 8")).toBeVisible());
  });

  it("disables every queue mutation control while a queue change is pending", async () => {
    const response = deferredResponse();
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = await queueRequest(input, init);
      if (request.url.pathname.endsWith("/order")) return response.promise;
      return jsonResponse(queueSnapshot);
    });

    await renderQueue();
    await screen.findByRole("button", { name: "task-first 操作" });
    openQueueMenu("task-first");
    fireEvent.click(await screen.findByRole("menuitem", { name: "下移" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "拖动 task-second" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "task-third 操作" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "拖动 task-active" })).toBeDisabled();

    response.resolve(jsonResponse({ ...queueSnapshot, revision: 8, queued: [queueSnapshot.queued[1], queueSnapshot.queued[0], queueSnapshot.queued[2]] }));
    await waitFor(() => expect(screen.getByRole("button", { name: "拖动 task-second" })).toBeEnabled());
  });

  it("reorders queued work through keyboard-only menu controls", async () => {
    const requests: { body: unknown; method: string; url: URL }[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = await queueRequest(input, init);
      requests.push(request);
      if (request.url.pathname.endsWith("/order")) return jsonResponse({ ...queueSnapshot, revision: 8, queued: [queueSnapshot.queued[1], queueSnapshot.queued[0], queueSnapshot.queued[2]] });
      return jsonResponse(queueSnapshot);
    });

    await renderQueue();
    await screen.findByRole("button", { name: "task-first 操作" });
    openQueueMenu("task-first");
    const moveDown = await screen.findByRole("menuitem", { name: "下移" });
    fireEvent.keyDown(moveDown, { key: "Enter" });

    await waitFor(() => expect(requests.some((request) => request.url.pathname.endsWith("/order"))).toBe(true));
    expect(screen.getAllByRole("row").map((row) => row.textContent).join(" ")).toMatch(/task-second[\s\S]*task-first/);
  });

  it("reorders queued work through the dnd-kit pointer sensor without moving the active entry", async () => {
    const requests: { body: unknown; method: string; url: URL }[] = [];
    installQueueRowLayout();
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = await queueRequest(input, init);
      requests.push(request);
      if (request.url.pathname.endsWith("/order")) return jsonResponse({ ...queueSnapshot, revision: 8, queued: [queueSnapshot.queued[1], queueSnapshot.queued[0], queueSnapshot.queued[2]] });
      return jsonResponse(queueSnapshot);
    });

    await renderQueue();
    const firstHandle = await screen.findByRole("button", { name: "拖动 task-first" });
    expect(screen.getByRole("button", { name: "拖动 task-active" })).toBeDisabled();

    fireEvent.pointerDown(firstHandle, { button: 0, clientX: 20, clientY: 20, isPrimary: true, pointerId: 1 });
    fireEvent.pointerMove(document, { clientX: 20, clientY: 68, isPrimary: true, pointerId: 1 });
    await waitFor(() => expect(firstHandle).toHaveAttribute("aria-pressed", "true"));
    fireEvent.pointerMove(document, { clientX: 20, clientY: 68, isPrimary: true, pointerId: 1 });
    fireEvent.pointerUp(document, { clientX: 20, clientY: 68, isPrimary: true, pointerId: 1 });

    await waitFor(() => expect(requests).toContainEqual(expect.objectContaining({ body: { expected_revision: 7, ordered_task_ids: ["task-second", "task-first", "task-third"] }, method: "PUT" })));
  });

  it("reorders queued work through the dnd-kit keyboard sensor", async () => {
    const requests: { body: unknown; method: string; url: URL }[] = [];
    installQueueRowLayout();
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = await queueRequest(input, init);
      requests.push(request);
      if (request.url.pathname.endsWith("/order")) return jsonResponse({ ...queueSnapshot, revision: 8, queued: [queueSnapshot.queued[1], queueSnapshot.queued[0], queueSnapshot.queued[2]] });
      return jsonResponse(queueSnapshot);
    });

    await renderQueue();
    const firstHandle = await screen.findByRole("button", { name: "拖动 task-first" });

    fireEvent.keyDown(firstHandle, { code: "Space", key: " " });
    await waitFor(() => expect(firstHandle).toHaveAttribute("aria-pressed", "true"));
    fireEvent.keyDown(document, { code: "ArrowDown", key: "ArrowDown" });
    fireEvent.keyDown(document, { code: "Space", key: " " });

    await waitFor(() => expect(requests).toContainEqual(expect.objectContaining({ body: { expected_revision: 7, ordered_task_ids: ["task-second", "task-first", "task-third"] }, method: "PUT" })));
  });

  it("promotes, pauses, and resumes an entry through explicit menu actions", async () => {
    const requests: { body: unknown; method: string; url: URL }[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = await queueRequest(input, init);
      requests.push(request);
      if (request.url.pathname.endsWith("/order")) return jsonResponse({ ...queueSnapshot, queued: [queueSnapshot.queued[2], queueSnapshot.queued[0], queueSnapshot.queued[1]], revision: 8 });
      if (request.url.pathname.endsWith("/task-third")) return jsonResponse({ ...queueSnapshot, paused: [queueSnapshot.queued[2], ...queueSnapshot.paused], queued: [queueSnapshot.queued[0], queueSnapshot.queued[1]], revision: 9 });
      if (request.url.pathname.endsWith("/task-paused")) return jsonResponse({ ...queueSnapshot, paused: [], queued: [...queueSnapshot.queued, queueSnapshot.paused[0]], revision: 10 });
      return jsonResponse(queueSnapshot);
    });

    await renderQueue();
    await screen.findByRole("button", { name: "task-third 操作" });
    openQueueMenu("task-third");
    fireEvent.click(await screen.findByRole("menuitem", { name: "移到队首" }));
    await waitFor(() => expect(requests).toContainEqual(expect.objectContaining({ body: { expected_revision: 7, ordered_task_ids: ["task-third", "task-first", "task-second"] }, method: "PUT" })));

    openQueueMenu("task-third");
    fireEvent.click(await screen.findByRole("menuitem", { name: "暂停" }));
    await waitFor(() => expect(requests).toContainEqual(expect.objectContaining({ body: { state: "paused" }, method: "PATCH", url: expect.objectContaining({ pathname: "/api/v2/queue/task-third" }) })));

    openQueueMenu("task-paused");
    fireEvent.click(await screen.findByRole("menuitem", { name: "恢复" }));
    await waitFor(() => expect(requests).toContainEqual(expect.objectContaining({ body: { state: "queued" }, method: "PATCH", url: expect.objectContaining({ pathname: "/api/v2/queue/task-paused" }) })));
  });

  it("keeps the active entry immovable and preserves a selected entry when a conflict restores the authoritative snapshot", async () => {
    const conflict = { ...queueSnapshot, queued: [queueSnapshot.queued[2], queueSnapshot.queued[0], queueSnapshot.queued[1]], revision: 8 };
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname.endsWith("/order")) return jsonResponse(conflict, 409);
      return jsonResponse(queueSnapshot);
    });

    await renderQueue();
    expect(await screen.findByRole("button", { name: "拖动 task-active" })).toBeDisabled();
    fireEvent.click(screen.getByRole("row", { name: /task-second/ }));
    expect(screen.getByRole("row", { name: /task-second/ })).toHaveAttribute("aria-selected", "true");

    openQueueMenu("task-first");
    fireEvent.click(await screen.findByRole("menuitem", { name: "下移" }));

    expect(await screen.findByText("队列已在其他操作中变化，已恢复最新顺序。")).toHaveAttribute("role", "status");
    expect(screen.getByRole("row", { name: /task-second/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByRole("row").map((row) => row.textContent).join(" ")).toMatch(/task-third[\s\S]*task-first[\s\S]*task-second/);
    expect(screen.getByText("队列版本 8")).toBeVisible();
  });
});
