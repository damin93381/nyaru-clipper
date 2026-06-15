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

const asrMissingModelStages = [
  { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
  { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
  { name: "asr", status: "failed", summary: "missing_model", failure_code: "asr_missing_model", attempts: 1 },
  { name: "translation", status: "pending", summary: null, attempts: 0 },
  { name: "highlight", status: "pending", summary: null, attempts: 0 },
  { name: "export", status: "pending", summary: null, attempts: 0 },
  { name: "report", status: "pending", summary: null, attempts: 0 },
];

function buildLogRecords(
  taskId: string,
  stageRows: Array<{ name: string; status: string; summary: string | null }>,
  overrides: Record<string, Partial<{ display_label: string; safe_summary: string | null; log_path: string }>> = {},
) {
  return stageRows.map((stage) => ({
    stage_name: stage.name,
    status: stage.status,
    summary: stage.summary,
    display_label: `${stage.name}.log`,
    safe_summary: stage.summary ?? "暂无阶段日志",
    log_path: `/data/tasks/${taskId}/logs/${stage.name}.log`,
    ...(overrides[stage.name] ?? {}),
  }));
}

async function registerTaskDetailRoutes(
  page,
  {
    artifacts = [],
    detailOverrides = {},
    logRecords,
    stageRows,
    status,
    taskId,
  }: {
    artifacts?: unknown[];
    detailOverrides?: Record<string, unknown>;
    logRecords?: unknown[];
    stageRows: Array<{ name: string; status: string; summary: string | null; attempts: number }>;
    status: string;
    taskId: string;
  },
) {
  const logs = logRecords ?? buildLogRecords(taskId, stageRows);

  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: taskId,
        source_url: `https://www.bilibili.com/video/${taskId}`,
        normalized_source_url: `https://www.bilibili.com/video/${taskId}`,
        source_video_id: taskId,
        status,
        stages: stageRows,
        log_records: logs,
        ...detailOverrides,
      }),
    });
  });

  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}/stages`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(stageRows),
    });
  });

  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}/artifacts`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(artifacts),
    });
  });

  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}/logs`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(logs),
    });
  });
}

test("renders a readable translation failure summary and retry-ready state @translation-failed", async ({ page }) => {
  await registerTaskDetailRoutes(page, {
    taskId: "task-failed123",
    status: "failed",
    stageRows: stages,
    artifacts: [
      {
        id: 1,
        task_id: "task-failed123",
        stage_name: "translation",
        kind: "bilingual_transcript_json",
        path: "/data/tasks/task-failed123/work/subtitles.zh-ja.json",
        metadata_json: '{"model_metadata":{"provider":"hf","model_name":"fixture-translator"}}',
      },
    ],
    logRecords: buildLogRecords("task-failed123", stages, {
      translation: { safe_summary: "translation_failed" },
    }),
  });

  await page.goto("/tasks/task-failed123");

  await expect(page.getByRole("heading", { level: 1, name: "Bilibili VTuber 工作台" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "任务 task-failed123" })).toBeVisible();
  await expect(page.getByText("恢复状态")).toBeVisible();
  await expect(page.getByText("翻译失败").first()).toBeVisible();
  await expect(page.getByText("可从 翻译 重新尝试。上游已成功阶段保持不变，下游阶段继续等待。")).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "阶段时间线" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "产物概览" })).toBeVisible();
  await expect(page.getByText(/bilingual_transcript_json/i)).toBeVisible();
  await expect(page.getByText(/fixture-translator/i)).toBeVisible();
});

test("ASR missing model shows download action and hides raw log path until disclosure @asr-missing-model", async ({ page }) => {
  const taskId = "task-asr-missing123";
  const rawAsrLogPath = "/home/drm/workfile/nyaru-clipper/data/tasks/task-asr-missing123/logs/asr.log";

  await registerTaskDetailRoutes(page, {
    taskId,
    status: "failed",
    stageRows: asrMissingModelStages,
    detailOverrides: {
      failure_code: "asr_missing_model",
      recovery_actions: [
        {
          id: "download_asr_model",
          enabled: true,
          method: "POST",
          endpoint: `/api/tasks/${taskId}/asr/models/download`,
        },
      ],
      failure_recovery: {
        stage: "asr",
        kind: "missing_model",
        message: "缺少 WhisperX 模型文件。",
        models: [
          {
            key: "whisperx",
            label: "WhisperX",
            status: "missing",
            target_dir: "data/models/whisperx",
            repo_id: "fixture/whisperx",
            download_supported: true,
          },
        ],
      },
    },
    logRecords: buildLogRecords(taskId, asrMissingModelStages, {
      asr: {
        display_label: "asr.log",
        safe_summary: "ASR 模型缺失，请下载模型后重试。",
        log_path: rawAsrLogPath,
      },
    }),
  });

  await page.goto(`/tasks/${taskId}`);

  await expect(page.getByRole("heading", { level: 3, name: "ASR 模型缺失" })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载缺失模型" })).toBeVisible();
  await expect(page.getByText("ASR 模型缺失，请下载模型后重试。")).toBeVisible();
  await expect(page.getByText(rawAsrLogPath)).not.toBeVisible();
  await expect(page.getByText("技术日志路径").first()).toBeVisible();
});

test("generic failed stage can be retried with the failed stage payload @generic-retry", async ({ page }) => {
  const taskId = "task-failed-retry123";
  let retryPayload: unknown = null;

  await registerTaskDetailRoutes(page, {
    taskId,
    status: "failed",
    stageRows: stages.map((stage) =>
      stage.name === "translation" ? { ...stage, failure_code: "unknown_failure" } : stage,
    ),
    detailOverrides: {
      failure_code: "unknown_failure",
      recovery_actions: [
        {
          id: "retry_stage",
          enabled: true,
          method: "POST",
          endpoint: `/api/tasks/${taskId}/retry`,
          payload: { stage_name: "translation" },
        },
      ],
    },
  });

  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}/retry`, async (route) => {
    retryPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ task_id: taskId, retry_stage: "translation", status: "pending" }),
    });
  });

  await page.goto(`/tasks/${taskId}`);

  await expect(page.getByRole("heading", { level: 3, name: "处理失败" })).toBeVisible();
  await page.getByRole("button", { name: "重试此阶段" }).click();
  await expect.poll(() => retryPayload).toEqual({ stage_name: "translation" });
});

test("task not found state offers a safe return action @task-not-found", async ({ page }) => {
  const taskId = "task-missing404";

  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}`, async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Task not found" }),
    });
  });
  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}/**`, async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Task not found" }),
    });
  });

  await page.goto(`/tasks/${taskId}`);

  await expect(page.getByRole("heading", { level: 2, name: "任务不存在" })).toBeVisible();
  await expect(page.getByRole("link", { name: "返回新建任务" })).toHaveAttribute("href", "/");
});
