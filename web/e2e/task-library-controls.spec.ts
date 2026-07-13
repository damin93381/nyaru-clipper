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

test("keeps the task-selection hit target large while rendering a compact paper-surface checkbox", async ({ page }) => {
  await page.route("**/api/v2/tasks/summary", async (route) => {
    await route.fulfill({ json: { active: 1, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 4_096 } });
  });
  await page.route(/\/api\/v2\/tasks(?:\?.*)?$/, async (route) => {
    await route.fulfill({ json: { items: [listItem], page: 1, page_count: 1, page_size: 50, total: 1 } });
  });

  await page.goto("/workstation");

  const selection = page.getByRole("checkbox", { name: "选择任务 夏日档案直播回放" });
  const selectionTarget = page.getByTestId("task-selection-target-task-42");
  const titleSort = page.getByRole("button", { exact: true, name: "任务" });
  await expect(selection).toBeVisible();
  await expect(titleSort).toBeVisible();

  const selectionBox = await selection.boundingBox();
  const selectionTargetBox = await selectionTarget.boundingBox();
  const titleSortBox = await titleSort.boundingBox();
  expect(selectionTargetBox?.width).toBeGreaterThanOrEqual(44);
  expect(selectionTargetBox?.height).toBeGreaterThanOrEqual(44);
  expect(selectionBox?.width).toBeGreaterThanOrEqual(16);
  expect(selectionBox?.width).toBeLessThanOrEqual(20);
  expect(selectionBox?.height).toBeGreaterThanOrEqual(16);
  expect(selectionBox?.height).toBeLessThanOrEqual(20);
  expect(titleSortBox?.width).toBeGreaterThanOrEqual(44);
  expect(titleSortBox?.height).toBeGreaterThanOrEqual(44);
  await expect(selection).toHaveCSS("appearance", "none");
  await expect(selection).toHaveCSS("border-top-width", "1px");
  await expect(selection).toHaveCSS("background-color", "rgb(253, 250, 243)");
  await selection.click();
  await expect(selection).toHaveCSS("background-color", "rgb(164, 60, 46)");

  await expect(page.getByRole("columnheader", { exact: true, name: "更新" })).toHaveAttribute("aria-sort", "descending");
  await expect(page.getByRole("columnheader", { exact: true, name: "任务" })).not.toHaveAttribute("aria-sort");
  await titleSort.click();
  await expect(page.getByRole("columnheader", { exact: true, name: "任务" })).toHaveAttribute("aria-sort", "descending");
  await titleSort.click();
  await expect(page.getByRole("columnheader", { exact: true, name: "任务" })).toHaveAttribute("aria-sort", "ascending");
});

test("keeps filter checkboxes in the workstation's light paper color scheme", async ({ page }) => {
  await page.route("**/api/v2/tasks/summary", async (route) => {
    await route.fulfill({ json: { active: 1, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 4_096 } });
  });
  await page.route(/\/api\/v2\/tasks(?:\?.*)?$/, async (route) => {
    await route.fulfill({ json: { items: [listItem], page: 1, page_count: 1, page_size: 50, total: 1 } });
  });

  await page.goto("/workstation");

  const workstation = page.getByRole("main");
  const running = page.getByRole("checkbox", { name: "运行中" });
  await expect(workstation).toHaveCSS("color-scheme", "light");
  await expect(running).toHaveCSS("appearance", "none");
  await expect(running).toHaveCSS("background-color", "rgb(253, 250, 243)");
  await expect(running).toHaveCSS("border-top-color", "rgb(201, 192, 176)");
  await running.click();
  await expect(running).toBeChecked();
  await expect(running).toHaveCSS("background-color", "rgb(164, 60, 46)");
  await expect(running).toHaveCSS("border-top-color", "rgb(164, 60, 46)");
});

test("searches and paginates a thousand-task library from the default entry", async ({ page }) => {
  const requests: URL[] = [];
  const firstPage = {
    archived_at: null,
    created_at: "2026-07-10T03:00:00Z",
    current_stage: "translation",
    progress_percent: 58,
    source_kind: "bilibili",
    source_label: "夏日档案直播",
    status: "running",
    storage_bytes: 4_096,
    tags: ["夏季"],
    task_id: "task-001",
    title: "夏日档案直播回放",
    updated_at: "2026-07-11T03:00:00Z",
  } as const;
  const secondPage = { ...firstPage, task_id: "task-026", title: "夏日档案检索结果" } as const;
  await page.route("**/api/v2/tasks/summary", async (route) => {
    await route.fulfill({ json: { active: 1, archived: 0, failed: 0, queued: 999, review_required: 0, storage_bytes: 4_096_000 } });
  });
  await page.route(/\/api\/v2\/tasks(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const pageNumber = url.searchParams.get("page");
    const query = url.searchParams.get("query");
    await route.fulfill({ json: pageNumber === "2"
      ? { items: [secondPage], page: 2, page_count: 40, page_size: 25, total: 1_000 }
      : { items: [firstPage], page: 1, page_count: 40, page_size: 25, total: query === "夏日" ? 1_000 : 1_000 } });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "任务库" })).toBeVisible();
  await page.getByRole("searchbox", { name: "搜索任务" }).fill("夏日");
  await expect.poll(() => requests.some((url) => url.searchParams.get("query") === "夏日")).toBe(true);
  await expect(page.getByText("第 1 / 40 页，共 1000 项")).toBeVisible();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("夏日档案检索结果")).toBeVisible();
  await expect(page).toHaveURL(/\?query=%E5%A4%8F%E6%97%A5&page=2$/);
  expect(requests.some((url) => url.searchParams.get("query") === "夏日" && url.searchParams.get("page") === "2")).toBe(true);
});
