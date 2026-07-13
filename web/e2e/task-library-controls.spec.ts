import { expect, test } from "@playwright/test";

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
  title: "夏日档案直播回放",
  updated_at: "2026-07-11T03:00:00Z",
} as const;

test("keeps task selection and sorting controls at the 44px target with correct aria-sort", async ({ page }) => {
  await page.route("**/api/v2/tasks/summary", async (route) => {
    await route.fulfill({ json: { active: 1, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 4_096 } });
  });
  await page.route(/\/api\/v2\/tasks(?:\?.*)?$/, async (route) => {
    await route.fulfill({ json: { items: [listItem], page: 1, page_count: 1, page_size: 50, total: 1 } });
  });

  await page.goto("/workstation");

  const selection = page.getByRole("checkbox", { name: "选择任务 夏日档案直播回放" });
  const titleSort = page.getByRole("button", { exact: true, name: "任务" });
  await expect(selection).toBeVisible();
  await expect(titleSort).toBeVisible();

  const selectionBox = await selection.boundingBox();
  const titleSortBox = await titleSort.boundingBox();
  expect(selectionBox?.width).toBeGreaterThanOrEqual(44);
  expect(selectionBox?.height).toBeGreaterThanOrEqual(44);
  expect(titleSortBox?.width).toBeGreaterThanOrEqual(44);
  expect(titleSortBox?.height).toBeGreaterThanOrEqual(44);

  await expect(page.getByRole("columnheader", { exact: true, name: "更新" })).toHaveAttribute("aria-sort", "descending");
  await expect(page.getByRole("columnheader", { exact: true, name: "任务" })).not.toHaveAttribute("aria-sort");
  await titleSort.click();
  await expect(page.getByRole("columnheader", { exact: true, name: "任务" })).toHaveAttribute("aria-sort", "descending");
  await titleSort.click();
  await expect(page.getByRole("columnheader", { exact: true, name: "任务" })).toHaveAttribute("aria-sort", "ascending");
});
