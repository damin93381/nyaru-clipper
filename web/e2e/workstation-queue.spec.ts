import { expect, test } from "@playwright/test";

const queueSnapshot = {
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
  await page.route("**/api/v2/queue**", async (route) => {
    if (route.request().method() === "PUT") {
      reorderBody = route.request().postDataJSON();
      await route.fulfill({ json: { ...queueSnapshot, queued: [
        { ...queueSnapshot.queued[1], position: 1 },
        { ...queueSnapshot.queued[0], position: 2 },
        queueSnapshot.queued[2],
      ], revision: 8 } });
      return;
    }
    await route.fulfill({ json: queueSnapshot });
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
});
