import { expect, test } from "@playwright/test";

const stages = [
  { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
  { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
  { name: "asr", status: "success", summary: "Generated aligned transcript and Chinese subtitles", attempts: 1 },
  { name: "translation", status: "failed", summary: "translation_failed", attempts: 2 },
  { name: "highlight", status: "pending", summary: null, attempts: 0 },
  { name: "export", status: "pending", summary: null, attempts: 0 },
  { name: "report", status: "pending", summary: null, attempts: 0 },
];

test("renders a readable translation failure summary and retry-ready state @translation-failed", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/api/tasks/task-failed123", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: "task-failed123",
        source_url: "https://www.bilibili.com/video/BV1failed123",
        normalized_source_url: "https://www.bilibili.com/video/BV1failed123",
        source_video_id: "BV1failed123",
        status: "failed",
        stages,
      }),
    });
  });

  await page.route("http://127.0.0.1:8000/api/tasks/task-failed123/stages", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(stages),
    });
  });

  await page.route("http://127.0.0.1:8000/api/tasks/task-failed123/artifacts", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: 1,
          task_id: "task-failed123",
          stage_name: "translation",
          kind: "bilingual_transcript_json",
          path: "/data/tasks/task-failed123/work/subtitles.zh-ja.json",
          metadata_json: '{"model_metadata":{"provider":"hf","model_name":"fixture-translator"}}',
        },
      ]),
    });
  });

  await page.route("http://127.0.0.1:8000/api/tasks/task-failed123/logs", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        stages.map((stage) => ({
          stage_name: stage.name,
          status: stage.status,
          summary: stage.name === "translation" ? "translation_failed" : stage.summary,
          log_path: `/data/tasks/task-failed123/logs/${stage.name}.log`,
        })),
      ),
    });
  });

  await page.goto("/tasks/task-failed123");

  await expect(page.getByRole("heading", { name: /task task-failed123/i })).toBeVisible();
  await expect(page.getByText(/translation stage failed/i)).toBeVisible();
  await expect(page.getByText(/retry-ready from translation/i)).toBeVisible();
  await expect(page.getByText(/bilingual_transcript_json/i)).toBeVisible();
  await expect(page.getByText(/fixture-translator/i)).toBeVisible();
});
