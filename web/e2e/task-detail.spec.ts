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

  await expect(page.getByRole("heading", { level: 1, name: "Bilibili VTuber 工作台" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "任务 task-failed123" })).toBeVisible();
  await expect(page.getByText("可读失败摘要")).toBeVisible();
  await expect(page.getByText("翻译阶段失败")).toBeVisible();
  await expect(page.getByText("可从 翻译 重新尝试。上游已成功阶段保持不变，下游阶段继续等待。")).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "阶段时间线" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "产物概览" })).toBeVisible();
  await expect(page.getByText(/bilingual_transcript_json/i)).toBeVisible();
  await expect(page.getByText(/fixture-translator/i)).toBeVisible();
});
