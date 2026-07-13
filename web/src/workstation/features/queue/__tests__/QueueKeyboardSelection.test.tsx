import { cleanup, fireEvent, screen } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContextInspector } from "../../../components/ContextInspector";
import { renderWorkstation } from "../../../testing/renderWorkstation";

const queueSnapshot = {
  active: null,
  paused: [],
  queued: [{ position: 1, priority: 0, state: "queued", task_id: "task-second" }],
  revision: 7,
} as const;

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
}

function LocationSearchProbe() {
  return <output aria-label="当前查询参数">{useLocation().search}</output>;
}

describe("Queue keyboard selection", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("updates the inspector and selected URL through the focusable row action", async () => {
    vi.stubGlobal("fetch", async () => jsonResponse(queueSnapshot));
    const { QueuePage } = await import("../QueuePage");

    renderWorkstation(<><QueuePage /><ContextInspector /><LocationSearchProbe /></>, { route: "/workstation/queue" });

    const selectionAction = await screen.findByRole("button", { name: "选择 task-second" });
    selectionAction.focus();
    expect(selectionAction).toHaveFocus();
    fireEvent.click(selectionAction);

    expect(await screen.findByRole("heading", { name: "已选队列项" })).toBeVisible();
    expect(screen.getByRole("row", { name: /task-second/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("当前查询参数")).toHaveTextContent("?selected=task-second");
  });
});
