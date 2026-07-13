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
