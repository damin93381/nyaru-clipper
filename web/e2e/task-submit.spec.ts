import { expect, test } from "@playwright/test";

const stages = [
  { name: "ingest", status: "pending", summary: null, attempts: 0 },
  { name: "media_prep", status: "pending", summary: null, attempts: 0 },
  { name: "asr", status: "pending", summary: null, attempts: 0 },
  { name: "translation", status: "pending", summary: null, attempts: 0 },
  { name: "highlight", status: "pending", summary: null, attempts: 0 },
  { name: "export", status: "pending", summary: null, attempts: 0 },
  { name: "report", status: "pending", summary: null, attempts: 0 },
];

test("submits a task and lands on the canonical detail page @happy", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/api/tasks", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }

    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: "task-happy123",
        source_url: "https://www.bilibili.com/video/BV1xx411c7mD",
        normalized_source_url: "https://www.bilibili.com/video/BV1xx411c7mD",
        source_video_id: "BV1xx411c7mD",
        status: "pending",
        stages,
        created: true,
      }),
    });
  });

  await page.route("http://127.0.0.1:8000/api/tasks/task-happy123", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: "task-happy123",
        source_url: "https://www.bilibili.com/video/BV1xx411c7mD",
        normalized_source_url: "https://www.bilibili.com/video/BV1xx411c7mD",
        source_video_id: "BV1xx411c7mD",
        status: "running",
        stages,
      }),
    });
  });

  await page.route("http://127.0.0.1:8000/api/tasks/task-happy123/stages", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(stages),
    });
  });

  await page.route("http://127.0.0.1:8000/api/tasks/task-happy123/artifacts", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.route("http://127.0.0.1:8000/api/tasks/task-happy123/logs", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        stages.map((stage) => ({
          stage_name: stage.name,
          status: stage.status,
          summary: stage.summary,
          log_path: `/data/tasks/task-happy123/logs/${stage.name}.log`,
        })),
      ),
    });
  });

  await page.goto("/");

  await page.getByTestId("task-url-input").fill("https://www.bilibili.com/video/BV1xx411c7mD");
  await page.getByTestId("task-submit-button").click();

  await expect(page).toHaveURL(/\/tasks\/task-happy123$/);
  await expect(page.getByRole("heading", { name: /task task-happy123/i })).toBeVisible();

  for (const stageName of ["ingest", "media_prep", "asr", "translation", "highlight", "export", "report"]) {
    await expect(page.getByRole("heading", { level: 4, name: new RegExp(stageName, "i") })).toBeVisible();
  }
});
