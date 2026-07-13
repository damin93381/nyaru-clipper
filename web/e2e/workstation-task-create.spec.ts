import { expect, test } from "@playwright/test";

test("creates an inspected Bilibili task through the production drawer", async ({ page }) => {
  let createBody: unknown;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v2/tasks" && method === "POST") {
      createBody = route.request().postDataJSON();
      await route.fulfill({ json: { priority: 4, profile_id: "standard", status: "pending", task_id: "task-e2e-created" }, status: 201 });
      return;
    }
    if (pathname === "/api/v2/sources/bilibili/inspect") {
      await route.fulfill({ json: { duration_seconds: 128, normalized_url: "https://www.bilibili.com/video/BV1e2ecreate", source_video_id: "BV1e2ecreate", title: "工作站创建验证", uploader: "Nyaru" } });
      return;
    }
    if (pathname === "/api/v2/processing-profiles") {
      await route.fulfill({ json: { profiles: [{ id: "standard", name: "Standard", stages: ["ingest", "media_prep", "asr"] }] } });
      return;
    }
    if (pathname === "/api/v2/tasks/summary") {
      await route.fulfill({ json: { active: 0, archived: 0, failed: 0, pending: 0, running: 0, total: 0 } });
      return;
    }
    if (pathname === "/api/v2/tasks") {
      await route.fulfill({ json: { items: [], page: 1, page_count: 1, page_size: 50, total: 0 } });
      return;
    }
    if (pathname === "/api/v2/queue") {
      await route.fulfill({ json: { active: null, paused: [], queued: [], revision: 1 } });
      return;
    }
    await route.fulfill({ json: {} });
  });

  await page.goto(`${process.env.WORKSTATION_E2E_BASE_URL ?? ""}/workstation`);
  await page.getByRole("button", { name: "新建任务" }).click();
  await page.getByRole("button", { name: "Bilibili 录播" }).click();
  await page.getByRole("textbox", { name: "Bilibili 链接" }).fill("https://www.bilibili.com/video/BV1e2ecreate");
  await page.getByRole("button", { name: "检查来源" }).click();
  await expect(page.getByText("工作站创建验证")).toBeVisible();
  await page.screenshot({ path: "/tmp/nyaru-task12-evidence/bilibili-preview.png", fullPage: true });
  await page.getByRole("button", { name: "继续设置" }).click();
  await page.getByRole("spinbutton", { name: "优先级" }).fill("4");
  await page.getByRole("button", { name: "创建任务" }).click();

  await expect(page).toHaveURL(/\/workstation\/tasks\/task-e2e-created$/);
  expect(createBody).toEqual({ priority: 4, profile_id: "standard", source: { kind: "bilibili", url: "https://www.bilibili.com/video/BV1e2ecreate" } });
});
