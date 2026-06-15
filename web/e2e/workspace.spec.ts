import { expect, test } from "@playwright/test";

const runningStages = [
  { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
  { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
  { name: "asr", status: "success", summary: "Generated aligned transcript and Chinese subtitles", attempts: 1 },
  { name: "translation", status: "success", summary: "Generated bilingual Chinese/Japanese subtitles", attempts: 1 },
  { name: "highlight", status: "success", summary: "Ranked 1 highlight candidate windows", attempts: 1 },
  { name: "export", status: "pending", summary: null, attempts: 0 },
  { name: "report", status: "success", summary: "Generated task report task-workspace123.md", attempts: 1 },
];

const zeroCandidateStages = [
  { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
  { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
  { name: "asr", status: "success", summary: "Generated aligned transcript and Chinese subtitles", attempts: 1 },
  { name: "translation", status: "success", summary: "Generated bilingual Chinese/Japanese subtitles", attempts: 1 },
  {
    name: "highlight",
    status: "success",
    summary: "No highlight candidates cleared the minimum score threshold from the available scene and subtitle signals.",
    attempts: 1,
  },
  { name: "export", status: "skipped", summary: "Waiting for user confirmation", attempts: 0 },
  { name: "report", status: "success", summary: "Generated task report task-zero123.md", attempts: 1 },
];

function artifactPath(taskId: string, artifactId: number, filename: string): string {
  return `/api/tasks/${taskId}/artifacts/${artifactId}/content/${filename}`;
}

async function registerCommonRoutes(
  page,
  taskId: string,
  stages,
  artifacts,
  options: { status?: string; artifactReadiness?: unknown[] } = {},
) {
  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: taskId,
        source_url: `https://www.bilibili.com/video/${taskId}`,
        normalized_source_url: `https://www.bilibili.com/video/${taskId}`,
        source_video_id: taskId,
        status: options.status ?? "success",
        stages,
        artifact_readiness: options.artifactReadiness,
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
      body: JSON.stringify(
        stages.map((stage) => ({
          stage_name: stage.name,
          status: stage.status,
          summary: stage.summary,
          log_path: `/data/tasks/${taskId}/logs/${stage.name}.log`,
        })),
      ),
    });
  });
}

test("confirms a candidate export and surfaces the downloadable clip card @export-candidate", async ({ page }) => {
  const taskId = "task-workspace123";
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
      metadata_json: '{"segment_count":2}',
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
  ];

  await registerCommonRoutes(page, taskId, runningStages, artifacts);

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

  await page.goto(`/tasks/${taskId}`);

  await expect(page.getByRole("heading", { level: 2, name: `任务 ${taskId}` })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "字幕审阅与高光确认" })).toBeVisible();
  await expect(page.getByText(`任务 ${taskId} 工作区`)).toBeVisible();
  await expect(page.getByRole("heading", { level: 4, name: "中文字幕与双语字幕行" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 4, name: "排名候选确认" })).toBeVisible();
  await expect(page.getByText(/seg-0001/i)).toBeVisible();
  await expect(page.getByText("こんにちは")).toBeVisible();
  await expect(page.getByText("开始（秒）")).toBeVisible();
  await expect(page.getByText("结束（秒）")).toBeVisible();
  await expect(page.getByRole("button", { name: "确认导出" })).toBeVisible();
  await expect(page.getByRole("link", { name: "下载双语字幕", exact: true })).toBeVisible();

  await page.getByTestId("candidate-start-input").fill("15.5");
  await page.getByTestId("candidate-end-input").fill("45");
  await page.getByTestId("candidate-confirm-button").click();

  await expect(page.getByText(/clip-00015500-00045000\.mp4/i)).toBeVisible();
  await expect(page.getByRole("link", { name: "下载已导出片段" })).toHaveAttribute(
    "href",
    `http://127.0.0.1:8000${artifactPath(taskId, 99, "clip-00015500-00045000.mp4")}`,
  );
});

test("shows zero-candidate state while preserving subtitle and report downloads @zero-candidate", async ({ page }) => {
  const taskId = "task-zero123";
  const artifacts = [
    {
      id: 1,
      task_id: taskId,
      stage_name: "asr",
      kind: "transcript_json",
      path: artifactPath(taskId, 1, "zero-asr-segments.json"),
      metadata_json: "{}",
    },
    {
      id: 2,
      task_id: taskId,
      stage_name: "translation",
      kind: "bilingual_transcript_json",
      path: artifactPath(taskId, 2, "zero-subtitles.zh-ja.json"),
      metadata_json: '{"segment_count":1}',
    },
    {
      id: 3,
      task_id: taskId,
      stage_name: "translation",
      kind: "bilingual_subtitle_srt",
      path: artifactPath(taskId, 3, "zero-subtitles.zh-ja.srt"),
      metadata_json: "{}",
    },
    {
      id: 4,
      task_id: taskId,
      stage_name: "highlight",
      kind: "highlight_candidates_json",
      path: artifactPath(taskId, 4, "zero-highlight-candidates.json"),
      metadata_json: '{"candidate_count":0,"no_candidates":"No highlight candidates cleared the minimum score threshold from the available scene and subtitle signals."}',
    },
    {
      id: 5,
      task_id: taskId,
      stage_name: "report",
      kind: "task_report_markdown",
      path: artifactPath(taskId, 5, "zero-task-report.md"),
      metadata_json: "{}",
    },
  ];

  await registerCommonRoutes(page, taskId, zeroCandidateStages, artifacts);

  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 1, "zero-asr-segments.json")}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        segments: [{ id: "seg-0007", start_seconds: 24, end_seconds: 28, text: "然后慢慢看下一个部分。" }],
      }),
    });
  });

  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 2, "zero-subtitles.zh-ja.json")}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        segments: [
          {
            id: "seg-0007",
            start_seconds: 24,
            end_seconds: 28,
            text: "然后慢慢看下一个部分。",
            translated_text: "それから次の部分をゆっくり見ます。",
          },
        ],
      }),
    });
  });

  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 4, "zero-highlight-candidates.json")}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        candidate_count: 0,
        no_candidates: "No highlight candidates cleared the minimum score threshold from the available scene and subtitle signals.",
        candidates: [],
      }),
    });
  });

  await page.goto(`/tasks/${taskId}`);

  await expect(page.getByRole("heading", { level: 2, name: `任务 ${taskId}` })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "字幕审阅与高光确认" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 4, name: "暂无可用高光候选" })).toBeVisible();
  await expect(page.getByText(/no highlight candidates cleared the minimum score threshold/i).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "下载双语字幕", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "下载任务报告" })).toBeVisible();
  await expect(page.getByTestId("candidate-confirm-button")).toHaveCount(0);
});

test("shows artifact not-ready readiness from the task contract @artifact-not-ready", async ({ page }) => {
  const taskId = "task-artifact-not-ready123";

  await registerCommonRoutes(page, taskId, runningStages, [], {
    status: "running",
    artifactReadiness: [
      { kind: "transcript_json", stage_name: "asr", status: "not_ready", artifact_id: null, path: null },
      {
        kind: "highlight_candidates_json",
        stage_name: "highlight",
        status: "not_ready",
        artifact_id: null,
        path: null,
      },
    ],
  });

  await page.goto(`/tasks/${taskId}`);

  await expect(page.getByRole("heading", { level: 2, name: `任务 ${taskId}` })).toBeVisible();
  await expect(page.getByText("该数据尚未生成").first()).toBeVisible();
});

test("shows artifact load errors with a section reload action @artifact-load-error", async ({ page }) => {
  const taskId = "task-artifact-load-error123";
  const artifacts = [
    {
      id: 1,
      task_id: taskId,
      stage_name: "asr",
      kind: "transcript_json",
      path: artifactPath(taskId, 1, "broken-asr-segments.json"),
      metadata_json: "{}",
    },
  ];

  await registerCommonRoutes(page, taskId, runningStages, artifacts, {
    artifactReadiness: [
      { kind: "transcript_json", stage_name: "asr", status: "ready", artifact_id: 1, path: artifacts[0].path },
    ],
  });
  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 1, "broken-asr-segments.json")}`, async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "artifact read failed" }),
    });
  });

  await page.goto(`/tasks/${taskId}`);

  await expect(page.getByText("加载工作台数据失败")).toBeVisible();
  await expect(page.getByRole("button", { name: "重新加载此区域" })).toBeVisible();
});

test("blocks invalid export ranges before sending a clips request @invalid-export-range", async ({ page }) => {
  const taskId = "task-invalid-export123";
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
      metadata_json: '{"segment_count":1}',
    },
    {
      id: 3,
      task_id: taskId,
      stage_name: "highlight",
      kind: "highlight_candidates_json",
      path: artifactPath(taskId, 3, "highlight-candidates.json"),
      metadata_json: '{"candidate_count":1}',
    },
  ];
  let clipsRequestCount = 0;

  await registerCommonRoutes(page, taskId, runningStages, artifacts);
  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 1, "asr-segments.json")}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 2, text: "你好" }] }),
    });
  });
  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 2, "subtitles.zh-ja.json")}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 2, text: "你好", translated_text: "こんにちは" }],
      }),
    });
  });
  await page.route(`http://127.0.0.1:8000${artifactPath(taskId, 3, "highlight-candidates.json")}`, async (route) => {
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
            reasons: ["laughter_phrase"],
            default_range: { start_s: 16, end_s: 44 },
          },
        ],
      }),
    });
  });
  await page.route(`http://127.0.0.1:8000/api/tasks/${taskId}/clips`, async (route) => {
    clipsRequestCount += 1;
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "clips should not be called" }),
    });
  });

  await page.goto(`/tasks/${taskId}`);

  await expect(page.getByRole("heading", { level: 4, name: "排名候选确认" })).toBeVisible();
  await page.getByTestId("candidate-start-input").fill("45");
  await page.getByTestId("candidate-end-input").fill("45");
  await page.getByTestId("candidate-confirm-button").click();

  await expect(page.getByText("开始时间必须早于结束时间")).toBeVisible();
  await expect.poll(() => clipsRequestCount).toBe(0);
});
