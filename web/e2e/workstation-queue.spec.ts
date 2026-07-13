import { expect, test } from "@playwright/test";

type QueueItem = {
  readonly position: number;
  readonly priority: number;
  readonly state: string;
  readonly task_id: string;
};

type QueueSnapshot = {
  readonly active: QueueItem | null;
  readonly paused: readonly QueueItem[];
  readonly queued: readonly QueueItem[];
  readonly revision: number;
};

const queueSnapshot: QueueSnapshot = {
  active: { position: 0, priority: 0, state: "running", task_id: "task-active" },
  paused: [],
  queued: [
    { position: 1, priority: 0, state: "queued", task_id: "task-first" },
    { position: 2, priority: 0, state: "queued", task_id: "task-second" },
    { position: 3, priority: 0, state: "queued", task_id: "task-third" },
  ],
  revision: 7,
} as const;

test("reorders only queued work with a real Chrome pointer drag", async ({ page }) => {
  let reorderBody: unknown;
  let latestQueueSnapshot = queueSnapshot;
  await page.route("**/api/v2/queue**", async (route) => {
    if (route.request().method() === "PUT") {
      reorderBody = route.request().postDataJSON();
      latestQueueSnapshot = {
        ...queueSnapshot,
        queued: [
          { ...queueSnapshot.queued[1], position: 1 },
          { ...queueSnapshot.queued[0], position: 2 },
          queueSnapshot.queued[2],
        ],
        revision: 8,
      };
      await route.fulfill({ json: latestQueueSnapshot });
      return;
    }
    await route.fulfill({ json: latestQueueSnapshot });
  });

  await page.goto("/workstation/queue");

  const activeHandle = page.getByRole("button", { name: "拖动 task-active" });
  const firstHandle = page.getByRole("button", { name: "拖动 task-first" });
  const secondHandle = page.getByRole("button", { name: "拖动 task-second" });
  await expect(activeHandle).toBeDisabled();
  await expect(firstHandle).toBeVisible();
  await expect(secondHandle).toBeVisible();

  const firstBox = await firstHandle.boundingBox();
  const secondBox = await secondHandle.boundingBox();
  expect(firstBox).not.toBeNull();
  expect(secondBox).not.toBeNull();
  if (firstBox === null || secondBox === null) throw new TypeError("Queue drag handles must have measurable boxes");

  await page.mouse.move(firstBox.x + firstBox.width / 2, firstBox.y + firstBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(firstBox.x + firstBox.width / 2, firstBox.y + firstBox.height / 2 + 8, { steps: 2 });
  await page.mouse.move(secondBox.x + secondBox.width / 2, secondBox.y + secondBox.height / 2, { steps: 8 });
  await page.mouse.up();

  await expect.poll(() => reorderBody).toEqual({ expected_revision: 7, ordered_task_ids: ["task-second", "task-first", "task-third"] });
  await expect(page.getByText("队列版本 8")).toBeVisible();
  await expect.poll(async () => (await page.locator("section[aria-labelledby='queue-list-title'] table").nth(1).locator("tbody tr").allTextContents()).map((text) => text.match(/task-\w+/)?.[0])).toEqual(["task-second", "task-first", "task-third"]);
});

test("reorders queued work with the real Chrome keyboard drag interaction", async ({ page }) => {
  let reorderBody: unknown;
  let latestQueueSnapshot = queueSnapshot;
  await page.route("**/api/v2/queue**", async (route) => {
    if (route.request().method() === "PUT") {
      reorderBody = route.request().postDataJSON();
      latestQueueSnapshot = {
        ...queueSnapshot,
        queued: [
          { ...queueSnapshot.queued[1], position: 1 },
          { ...queueSnapshot.queued[0], position: 2 },
          queueSnapshot.queued[2],
        ],
        revision: 8,
      };
      await route.fulfill({ json: latestQueueSnapshot });
      return;
    }
    await route.fulfill({ json: latestQueueSnapshot });
  });

  await page.setViewportSize({ height: 800, width: 1280 });
  await page.goto("/workstation/queue");
  const firstHandle = page.getByRole("button", { name: "拖动 task-first" });
  await firstHandle.focus();
  await firstHandle.press("Space");
  await expect(firstHandle).toHaveAttribute("aria-pressed", "true");
  await firstHandle.press("ArrowDown");
  await expect(page.getByRole("row", { name: /task-second/ })).toHaveAttribute("data-queue-insertion", "after");
  await firstHandle.press("Space");

  await expect.poll(() => reorderBody).toEqual({ expected_revision: 7, ordered_task_ids: ["task-second", "task-first", "task-third"] });
  await expect(page.getByText("队列版本 8")).toBeVisible();
});

test("shows queue inspection, drag affordances, and disabled menu states in production Chrome", async ({ page }) => {
  await page.route("**/api/v2/queue**", async (route) => route.fulfill({ json: queueSnapshot }));

  await page.goto("/workstation/queue");

  await page.getByRole("row", { name: /task-second/ }).click();
  await expect(page.getByRole("complementary", { name: "上下文检查器" }).getByRole("heading", { name: "已选队列项" })).toBeVisible();
  await expect(page.getByRole("button", { name: "task-active 操作" })).toHaveCount(0);
  await expect(page.getByText("执行中，当前不可调整。")).toBeVisible();

  const firstHandle = page.getByRole("button", { name: "拖动 task-first" });
  const secondHandle = page.getByRole("button", { name: "拖动 task-second" });
  const firstBox = await firstHandle.boundingBox();
  const secondBox = await secondHandle.boundingBox();
  expect(firstBox).not.toBeNull();
  expect(secondBox).not.toBeNull();
  if (firstBox === null || secondBox === null) throw new TypeError("Queue drag handles must have measurable boxes");

  await page.mouse.move(firstBox.x + firstBox.width / 2, firstBox.y + firstBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(firstBox.x + firstBox.width / 2, firstBox.y + firstBox.height / 2 + 8, { steps: 2 });
  await page.mouse.move(secondBox.x + secondBox.width / 2, secondBox.y + secondBox.height / 2, { steps: 8 });
  await expect(page.getByRole("row", { name: /task-first/ })).toHaveAttribute("data-queue-drag-source", "true");
  await expect(page.getByRole("row", { name: /task-second/ })).toHaveAttribute("data-queue-insertion", "after");
  await page.screenshot({ path: "../.superpowers/sdd/task-11-queue-drag-state.png", fullPage: true });
  await page.mouse.up();

  await page.getByRole("button", { name: "task-first 操作" }).press("ArrowDown");
  const moveUp = page.getByRole("menuitem", { name: "上移" });
  await expect(moveUp).toHaveAttribute("data-disabled", "");
  await expect(moveUp).toHaveCSS("cursor", "not-allowed");
});

test("selects a queue entry with Enter and updates the persistent inspector URL", async ({ page }) => {
  await page.route("**/api/v2/queue**", async (route) => route.fulfill({ json: queueSnapshot }));

  await page.goto("/workstation/queue");

  const selectionAction = page.getByRole("button", { name: "选择 task-second" });
  await selectionAction.focus();
  const selectionBox = await selectionAction.boundingBox();
  expect(selectionBox?.height).toBeGreaterThanOrEqual(44);
  await expect(selectionAction).toBeFocused();
  await selectionAction.press("Enter");

  await expect(page).toHaveURL(/\/workstation\/queue\?selected=task-second$/);
  await expect(page.getByRole("complementary", { name: "上下文检查器" }).getByRole("heading", { name: "已选队列项" })).toBeVisible();
  await expect(selectionAction).toHaveAttribute("aria-pressed", "true");
});

test("rolls back a conflicting queue reorder to the authoritative order", async ({ page }) => {
  const conflictSnapshot: QueueSnapshot = {
    ...queueSnapshot,
    queued: [
      { ...queueSnapshot.queued[2], position: 1 },
      { ...queueSnapshot.queued[0], position: 2 },
      { ...queueSnapshot.queued[1], position: 3 },
    ],
    revision: 8,
  };
  let reorderBody: unknown;
  let returnedConflict = false;
  await page.route("**/api/v2/queue**", async (route) => {
    if (route.request().method() === "PUT") {
      reorderBody = route.request().postDataJSON();
      returnedConflict = true;
      await route.fulfill({ json: conflictSnapshot, status: 409 });
      return;
    }
    await route.fulfill({ json: returnedConflict ? conflictSnapshot : queueSnapshot });
  });

  await page.goto("/workstation/queue");
  await page.getByRole("button", { name: "task-first 操作" }).click();
  await page.getByRole("menuitem", { name: "下移" }).click();

  await expect.poll(() => reorderBody).toEqual({ expected_revision: 7, ordered_task_ids: ["task-second", "task-first", "task-third"] });
  await expect(page.getByText("队列已在其他操作中变化，已恢复最新顺序。")).toHaveAttribute("role", "status");
  await expect(page.getByText("队列版本 8")).toBeVisible();
  const authoritativeOrder = (await page.getByRole("row").allTextContents())
    .filter((text) => /task-(third|first|second)/.test(text))
    .map((text) => text.match(/task-(third|first|second)/)?.[0]);
  expect(authoritativeOrder).toEqual(["task-third", "task-first", "task-second"]);
});
