import { expect, test } from "@playwright/test";

const stageHeadings = ["采集", "媒体准备", "语音转写", "翻译", "高光", "导出", "报告"];

const pendingStages = [
  { name: "ingest", status: "pending", summary: null, attempts: 0 },
  { name: "media_prep", status: "pending", summary: null, attempts: 0 },
  { name: "asr", status: "pending", summary: null, attempts: 0 },
  { name: "translation", status: "pending", summary: null, attempts: 0 },
  { name: "highlight", status: "pending", summary: null, attempts: 0 },
  { name: "export", status: "pending", summary: null, attempts: 0 },
  { name: "report", status: "pending", summary: null, attempts: 0 },
] as const;

const happyStages = [
  { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
  { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
  { name: "asr", status: "success", summary: "Generated aligned transcript and Chinese subtitles", attempts: 1 },
  { name: "translation", status: "success", summary: "Generated bilingual Chinese/Japanese subtitles", attempts: 1 },
  { name: "highlight", status: "success", summary: "Ranked 1 highlight candidate windows", attempts: 1 },
  { name: "export", status: "pending", summary: null, attempts: 0 },
  { name: "report", status: "success", summary: "Generated task report task-flow-happy123.md", attempts: 1 },
] as const;

const translationFailedStages = [
  { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
  { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
  { name: "asr", status: "success", summary: "Generated aligned transcript and Chinese subtitles", attempts: 1 },
  { name: "translation", status: "failed", summary: "translation_failed", attempts: 2 },
  { name: "highlight", status: "pending", summary: null, attempts: 0 },
  { name: "export", status: "pending", summary: null, attempts: 0 },
  { name: "report", status: "pending", summary: null, attempts: 0 },
] as const;

function buildLogs(taskId: string, stages: readonly { name: string; status: string; summary: string | null }[]) {
  return stages.map((stage) => ({
    stage_name: stage.name,
    status: stage.status,
    summary: stage.summary,
    log_path: `/data/tasks/${taskId}/logs/${stage.name}.log`,
  }));
}

async function registerTaskRoutes(
  page,
  {
    taskId,
    status,
    stages,
    artifacts,
    logs = buildLogs(taskId, stages),
  }: {
    taskId: string;
    status: string;
    stages: readonly { name: string; status: string; summary: string | null; attempts: number }[];
    artifacts: readonly {
      id: number;
      task_id: string;
      stage_name: string;
      kind: string;
      path: string;
      metadata_json: string;
    }[];
    logs?: readonly {
      stage_name: string;
      status: string;
      summary: string | null;
      log_path: string;
    }[];
  },
) {
  const sourceUrl = `https://www.bilibili.com/video/${taskId}`;

  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: taskId,
        source_url: sourceUrl,
        normalized_source_url: sourceUrl,
        source_video_id: taskId,
        status,
        stages,
      }),
    });
  });

  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}/stages`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(stages),
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

function artifactPath(taskId: string, artifactId: number, filename: string): string {
  return `/api/tasks/${taskId}/artifacts/${artifactId}/content/${filename}`;
}

test("submits a task, lands on the canonical detail page, and completes workspace export @happy", async ({ page }) => {
  const taskId = "task-flow-happy123";
  const artifacts = [
    {
      id: 1,
      task_id: taskId,
      stage_name: "asr",
      kind: "transcript_json",
      path: artifactPath(taskId, 1, "asr-segments.json"),
      metadata_json: "{}",
    },
    {
      id: 2,
      task_id: taskId,
      stage_name: "translation",
      kind: "bilingual_transcript_json",
      path: artifactPath(taskId, 2, "subtitles.zh-ja.json"),
      metadata_json: '{"segment_count":2,"model_metadata":{"provider":"hf","model_name":"fixture-translator"}}',
    },
    {
      id: 3,
      task_id: taskId,
      stage_name: "translation",
      kind: "bilingual_subtitle_srt",
      path: artifactPath(taskId, 3, "subtitles.zh-ja.srt"),
      metadata_json: "{}",
    },
    {
      id: 4,
      task_id: taskId,
      stage_name: "highlight",
      kind: "highlight_candidates_json",
      path: artifactPath(taskId, 4, "highlight-candidates.json"),
      metadata_json: '{"candidate_count":1}',
    },
    {
      id: 5,
      task_id: taskId,
      stage_name: "report",
      kind: "task_report_markdown",
      path: artifactPath(taskId, 5, "task-report.md"),
      metadata_json: "{}",
    },
  ] as const;

  let submittedClipPayload: unknown = null;

  await page.route("http://127.0.0.1:8000/api/tasks", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }

    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: taskId,
        source_url: "https://www.bilibili.com/video/BV1flowhappy123",
        normalized_source_url: "https://www.bilibili.com/video/BV1flowhappy123",
        source_video_id: "BV1flowhappy123",
        status: "pending",
        stages: pendingStages,
        created: true,
      }),
    });
  });

  await registerTaskRoutes(page, {
    taskId,
    status: "success",
    stages: happyStages,
    artifacts,
  });

  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 1, "asr-segments.json")}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        segments: [
          { id: "seg-0001", start_seconds: 0, end_seconds: 1.4, text: "你好" },
          { id: "seg-0002", start_seconds: 1.4, end_seconds: 3, text: "世界" },
        ],
      }),
    });
  });

  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 2, "subtitles.zh-ja.json")}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        segments: [
          { id: "seg-0001", start_seconds: 0, end_seconds: 1.4, text: "你好", translated_text: "こんにちは" },
          { id: "seg-0002", start_seconds: 1.4, end_seconds: 3, text: "世界", translated_text: "世界" },
        ],
      }),
    });
  });

  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 4, "highlight-candidates.json")}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        candidate_count: 1,
        no_candidates: null,
        candidates: [
          {
            candidate_id: 41,
            rank: 1,
            start_s: 18,
            end_s: 42,
            score: 0.91,
            reasons: ["laughter_phrase", "emphasis_punctuation"],
            default_range: { start_s: 16, end_s: 44 },
          },
        ],
      }),
    });
  });

  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}/clips`, async (route) => {
    submittedClipPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: taskId,
        candidate_id: 41,
        start_s: 15.5,
        end_s: 45,
        path: artifactPath(taskId, 99, "clip-00015500-00045000.mp4"),
        filename: "clip-00015500-00045000.mp4",
        artifact_id: 99,
      }),
    });
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Bilibili VTuber 工作台" })).toBeVisible();
  await expect(page.getByRole("link", { name: "新建任务" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "将 Bilibili 录播加入标准工作流水线" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "创建任务" })).toBeVisible();
  await expect(page.getByRole("button", { name: "创建任务" })).toBeVisible();

  await page.getByTestId("task-url-input").fill("https://www.bilibili.com/video/BV1flowhappy123");
  await page.getByTestId("task-submit-button").click();

  await expect(page).toHaveURL(new RegExp(`/tasks/${taskId}$`));
  await expect(page.getByRole("heading", { level: 2, name: `任务 ${taskId}` })).toBeVisible();
  await expect(page.getByText("任务详情")).toBeVisible();

  for (const stageName of stageHeadings) {
    await expect(page.getByRole("heading", { level: 4, name: stageName })).toBeVisible();
  }

  await expect(page.getByRole("heading", { level: 3, name: "字幕审阅与高光确认" })).toBeVisible();
  await expect(page.getByText(`任务 ${taskId} 工作区`)).toBeVisible();
  await expect(page.getByRole("heading", { level: 4, name: "中文字幕与双语字幕行" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 4, name: "排名候选确认" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 4, name: "产物下载" })).toBeVisible();
  await expect(page.getByText(/seg-0001/i)).toBeVisible();
  await expect(page.getByText("こんにちは")).toBeVisible();
  await expect(page.getByText("笑声片段")).toBeVisible();
  await expect(page.getByText("强调标点")).toBeVisible();
  await expect(page.getByText("开始（秒）")).toBeVisible();
  await expect(page.getByText("结束（秒）")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认导出" })).toBeVisible();
  await expect(page.getByRole("link", { name: "下载双语字幕", exact: true })).toHaveAttribute(
    "href",
    `http://127.0.0.1:8000${artifactPath(taskId, 3, "subtitles.zh-ja.srt")}`,
  );
  await expect(page.getByRole("link", { name: "下载任务报告" })).toHaveAttribute(
    "href",
    `http://127.0.0.1:8000${artifactPath(taskId, 5, "task-report.md")}`,
  );

  await page.getByTestId("candidate-start-input").fill("15.5");
  await page.getByTestId("candidate-end-input").fill("45");
  await page.getByTestId("candidate-confirm-button").click();

  await expect.poll(() => submittedClipPayload).toEqual({
    candidate_id: 41,
    start_s: 15.5,
    end_s: 45,
  });
  await expect(page.getByText(/clip-00015500-00045000\.mp4/i)).toBeVisible();
  await expect(page.getByRole("link", { name: "下载已导出片段" })).toHaveAttribute(
    "href",
    `http://127.0.0.1:8000${artifactPath(taskId, 99, "clip-00015500-00045000.mp4")}`,
  );
});

test("renders the translation-failed detail state with deterministic evidence fixtures @translation-failed", async ({ page }) => {
  const taskId = "task-flow-failed123";
  const artifacts = [
    {
      id: 1,
      task_id: taskId,
      stage_name: "translation",
      kind: "bilingual_transcript_json",
      path: artifactPath(taskId, 1, "subtitles.zh-ja.json"),
      metadata_json: '{"segment_count":2,"model_metadata":{"provider":"hf","model_name":"fixture-translator"}}',
    },
    {
      id: 2,
      task_id: taskId,
      stage_name: "translation",
      kind: "bilingual_subtitle_srt",
      path: artifactPath(taskId, 2, "subtitles.zh-ja.srt"),
      metadata_json: "{}",
    },
  ] as const;

  await registerTaskRoutes(page, {
    taskId,
    status: "failed",
    stages: translationFailedStages,
    artifacts,
    logs: translationFailedStages.map((stage) => ({
      stage_name: stage.name,
      status: stage.status,
      summary: stage.name === "translation" ? "translation_failed" : stage.summary,
      log_path: `/data/tasks/${taskId}/logs/${stage.name}.log`,
    })),
  });

  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 1, "subtitles.zh-ja.json")}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        segment_count: 2,
        model_metadata: { provider: "hf", model_name: "fixture-translator" },
        segments: [
          {
            id: "seg-fail-0001",
            start_seconds: 12,
            end_seconds: 15.2,
            text: "翻译失败前的保留字幕。",
            translated_text: "翻訳失敗前の保持字幕。",
          },
          {
            id: "seg-fail-0002",
            start_seconds: 15.2,
            end_seconds: 18.5,
            text: "可以从这里重新开始。",
            translated_text: "ここから再開できます。",
          },
        ],
      }),
    });
  });

	await page.goto(`/tasks/${taskId}`);

	await expect(page.getByRole("heading", { level: 2, name: `任务 ${taskId}` })).toBeVisible();
	const failurePanel = page.locator(".panel").filter({
		has: page.getByRole("heading", { level: 3, name: "处理失败" }),
	});
	await expect(failurePanel.getByText("翻译失败", { exact: true })).toBeVisible();
	await expect(failurePanel.getByText("可从 翻译 重新尝试。上游已成功阶段保持不变，下游阶段继续等待。")).toBeVisible();
  await expect(page.getByText(/bilingual_transcript_json/i)).toBeVisible();
  await expect(page.getByText(/fixture-translator/i)).toBeVisible();
  await expect(page.getByText(/seg-fail-0001/i)).toBeVisible();
  await expect(page.getByText("翻訳失敗前の保持字幕。")).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "字幕审阅与高光确认" })).toBeVisible();
  await expect(page.getByRole("link", { name: "下载双语字幕", exact: true })).toHaveAttribute(
    "href",
    `http://127.0.0.1:8000${artifactPath(taskId, 2, "subtitles.zh-ja.srt")}`,
  );
  await expect(page.getByTestId("candidate-confirm-button")).toHaveCount(0);
});
