import { expect, test } from "@playwright/test";

test("creates an inspected Bilibili task and exposes it in the ordered queue", async ({ page }) => {
  let createBody: unknown;
  let created = false;
  await page.route("http://127.0.0.1:8000/api/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v2/tasks" && method === "POST") {
      createBody = route.request().postDataJSON();
      created = true;
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
      await route.fulfill({ json: { active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 } });
      return;
    }
    if (pathname === "/api/v2/tasks") {
      await route.fulfill({ json: { items: [], page: 1, page_count: 1, page_size: 50, total: 0 } });
      return;
    }
    if (pathname === "/api/v2/queue") {
      await route.fulfill({ json: created
        ? { active: null, paused: [], queued: [{ position: 1, priority: 4, state: "queued", task_id: "task-e2e-created" }], revision: 2 }
        : { active: null, paused: [], queued: [], revision: 1 } });
      return;
    }
    await route.fulfill({ json: {} });
  });

  await page.goto(`${process.env.WORKSTATION_E2E_BASE_URL ?? ""}/workstation`);
  await expect(page.getByLabel("任务库摘要")).toContainText("队列中 0");
  await expect(page.getByRole("main")).not.toContainText("undefined");
  await expect(page.getByRole("main")).not.toContainText("NaN");
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
  expect(createBody).toEqual({ highlight_filtering_enabled: false, priority: 4, profile_id: "standard", source: { kind: "bilibili", url: "https://www.bilibili.com/video/BV1e2ecreate" } });
  await page.goto("/workstation/queue");
  await expect(page.getByText("队列版本 2")).toBeVisible();
  await expect(page.getByRole("row", { name: /task-e2e-created/ })).toBeVisible();
});

test("creates a referenced local-file task from a trusted root", async ({ page }) => {
  let createBody: unknown;
  await page.route("http://127.0.0.1:8000/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v2/tasks" && request.method() === "POST") {
      createBody = request.postDataJSON();
      await route.fulfill({ json: { priority: 0, profile_id: "standard", status: "pending", task_id: "task-local-reference" }, status: 201 });
      return;
    }
    if (pathname === "/api/v2/sources/local") {
      const rootId = new URL(request.url()).searchParams.get("root_id");
      await route.fulfill({ json: rootId === null
        ? { entries: [], relative_path: "", root_id: null, roots: [{ id: "trusted-media", name: "受信任媒体" }] }
        : { entries: [{ kind: "file", name: "episode-01.mp4", relative_path: "archive/episode-01.mp4" }], relative_path: "", root_id: "trusted-media", roots: [{ id: "trusted-media", name: "受信任媒体" }] } });
      return;
    }
    if (pathname === "/api/v2/processing-profiles") {
      await route.fulfill({ json: { profiles: [{ id: "standard", name: "Standard", stages: ["ingest", "media_prep", "asr"] }] } });
      return;
    }
    if (pathname === "/api/v2/tasks/summary") {
      await route.fulfill({ json: { active: 0, archived: 0, failed: 0, queued: 0, review_required: 0, storage_bytes: 0 } });
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

  await page.goto("/workstation");
  await page.getByRole("button", { name: "新建任务" }).click();
  await page.getByRole("button", { name: "本地文件" }).click();
  await page.getByRole("button", { name: "受信任媒体" }).click();
  await page.getByRole("button", { name: "episode-01.mp4" }).click();
  await expect(page.getByRole("region", { name: "已选本地来源" })).toContainText("episode-01.mp4");
  await expect(page.getByRole("radio", { name: "引用原始文件" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "继续设置" }).click();
  await page.getByRole("button", { name: "创建任务" }).click();

  await expect(page).toHaveURL(/\/workstation\/tasks\/task-local-reference$/);
  expect(createBody).toEqual({
    highlight_filtering_enabled: false,
    priority: 0,
    profile_id: "standard",
    source: { import_mode: "reference", kind: "local", relative_path: "archive/episode-01.mp4", root_id: "trusted-media" },
  });
});
