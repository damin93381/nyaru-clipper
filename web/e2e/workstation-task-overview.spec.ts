import { expect, test } from "@playwright/test";

const taskOverview = {
  archived_at: null,
  artifact_readiness: [
    { artifact_id: 1, kind: "transcript_json", path: "/api/tasks/task-e2e-overview/artifacts/1/content/asr-segments.json", stage_name: "asr", status: "ready" },
    { artifact_id: 2, kind: "bilingual_transcript_json", path: "/api/tasks/task-e2e-overview/artifacts/2/content/subtitles.zh-ja.json", stage_name: "translation", status: "ready" },
    { artifact_id: 3, kind: "highlight_candidates_json", path: "/api/tasks/task-e2e-overview/artifacts/3/content/highlight-candidates.json", stage_name: "highlight", status: "ready" },
  ],
  artifacts: [
    { artifact_id: 1, created_at: "2026-07-12T03:00:00Z", kind: "transcript_json", metadata_json: "{}", path: "/api/tasks/task-e2e-overview/artifacts/1/content/asr-segments.json", stage_name: "asr" },
    { artifact_id: 2, created_at: "2026-07-12T03:00:00Z", kind: "bilingual_transcript_json", metadata_json: "{}", path: "/api/tasks/task-e2e-overview/artifacts/2/content/subtitles.zh-ja.json", stage_name: "translation" },
    { artifact_id: 3, created_at: "2026-07-12T03:00:00Z", kind: "highlight_candidates_json", metadata_json: "{}", path: "/api/tasks/task-e2e-overview/artifacts/3/content/highlight-candidates.json", stage_name: "highlight" },
  ],
  created_at: "2026-07-12T03:00:00Z",
  current_stage: "asr",
  execution_progress: { current_phase: "align", heartbeat_at: "2026-07-12T03:03:00Z", latest_message: "正在校准字幕时间轴", phase_count: 5, phase_index: 4, phase_started_at: "2026-07-12T03:02:00Z", phases: [], stage_name: "asr" },
  pipeline_run_id: "run-e2e",
  progress_percent: 58,
  recovery_actions: [],
  safe_logs: [{ display_label: "ASR 转写", stage_name: "asr", status: "running", summary: "已写入可公开的转写进度摘要" }],
  source_kind: "bilibili",
  source_label: "Windows Chrome 工作站验证",
  stages: [
    { attempts: 1, failure_code: null, finished_at: "2026-07-12T03:01:00Z", name: "ingest", planned: false, started_at: "2026-07-12T03:00:00Z", status: "success", summary: "已采集" },
    { attempts: 1, failure_code: null, finished_at: "2026-07-12T03:02:00Z", name: "media_prep", planned: false, started_at: "2026-07-12T03:01:00Z", status: "success", summary: "已准备" },
    { attempts: 1, failure_code: null, finished_at: null, name: "asr", planned: false, started_at: "2026-07-12T03:02:00Z", status: "running", summary: "正在转写" },
    { attempts: 0, failure_code: null, finished_at: null, name: "translation", planned: true, started_at: null, status: "pending", summary: null },
    { attempts: 0, failure_code: null, finished_at: null, name: "highlight", planned: true, started_at: null, status: "pending", summary: null },
    { attempts: 0, failure_code: null, finished_at: null, name: "export", planned: true, started_at: null, status: "pending", summary: null },
    { attempts: 0, failure_code: null, finished_at: null, name: "report", planned: true, started_at: null, status: "pending", summary: null },
  ],
  status: "running",
  storage_bytes: 4_096,
  tags: [],
  task_id: "task-e2e-overview",
  title: "工作站任务概览验证",
  updated_at: "2026-07-12T03:03:00Z",
} as const;

test("renders the task overview and selected-stage inspector in production Chrome", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v2/tasks/task-e2e-overview") return route.fulfill({ json: taskOverview });
    if (pathname.endsWith("asr-segments.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "你好，欢迎来到单用户剪辑工作站。" }] } });
    if (pathname.endsWith("subtitles.zh-ja.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "你好，欢迎来到单用户剪辑工作站。", translated_text: "こんにちは" }] } });
    if (pathname.endsWith("highlight-candidates.json")) return route.fulfill({ json: { candidate_count: 0, candidates: [], no_candidates: "暂无高光候选" } });
    return route.fulfill({ json: {} });
  });

  await page.goto(`${process.env.WORKSTATION_E2E_BASE_URL ?? ""}/workstation/tasks/task-e2e-overview`);

  await expect(page.getByRole("heading", { name: "工作站任务概览验证" })).toBeVisible();
  await expect(page.getByText("校准字幕时间轴 · 4 / 5")).toBeVisible();
  await expect(page.getByRole("button", { name: /语音转写/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("complementary", { name: "上下文检查器" }).getByText("已写入可公开的转写进度摘要")).toBeVisible();
  const sourceSubtitle = page.getByText("你好，欢迎来到单用户剪辑工作站。");
  await expect(sourceSubtitle).toBeVisible();
  expect(await sourceSubtitle.evaluate((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    return range.getClientRects().length;
  })).toBe(1);
  await expect(page.getByText("こんにちは")).toBeVisible();
  await page.screenshot({ path: "/tmp/nyaru-task13-evidence/overview-running.png", fullPage: true });

  await page.getByRole("button", { name: /翻译/ }).click();
  await expect(page).toHaveURL(/stage=translation$/);
  await expect(page.getByRole("complementary", { name: "上下文检查器" }).getByText("双语字幕数据")).toBeVisible();
  await page.screenshot({ path: "/tmp/nyaru-task13-evidence/overview-stage-selected.png", fullPage: true });
});

test("keeps a Japanese title clause unbroken at the compact desktop width", async ({ page }) => {
  const title = "映像の中にある字幕レビューを確認する";
  const japaneseOverview = { ...taskOverview, title };
  await page.setViewportSize({ height: 900, width: 1280 });
  await page.route("http://127.0.0.1:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v2/tasks/task-e2e-overview") return route.fulfill({ json: japaneseOverview });
    if (pathname.endsWith("asr-segments.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "こんにちは" }] } });
    if (pathname.endsWith("subtitles.zh-ja.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "こんにちは", translated_text: "字幕" }] } });
    if (pathname.endsWith("highlight-candidates.json")) return route.fulfill({ json: { candidate_count: 0, candidates: [], no_candidates: "候補はありません" } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/workstation/tasks/task-e2e-overview");

  const heading = page.getByRole("heading", { name: title });
  const locationClause = heading.locator(".ny-task-overview__title-phrase", { hasText: "映像の中にある" });
  const reviewClause = heading.locator(".ny-task-overview__title-phrase", { hasText: "字幕レビューを確認する" });
  await expect(heading).toBeVisible();
  await expect(locationClause).toHaveText("映像の中にある");
  await expect(reviewClause).toHaveText("字幕レビューを確認する");
  expect(await locationClause.evaluate((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    return range.getClientRects().length;
  })).toBe(1);
  expect(await reviewClause.evaluate((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    return range.getClientRects().length;
  })).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.screenshot({ path: "/tmp/nyaru-japanese-title-evidence/task-overview-1280.png", fullPage: true });
});

test("moves a Japanese particle with its content at the twelve-character boundary", async ({ page }) => {
  const title = "映像の字幕の確認の場面の表示を確認する";
  const boundaryOverview = { ...taskOverview, title };
  await page.setViewportSize({ height: 900, width: 1280 });
  await page.route("http://127.0.0.1:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v2/tasks/task-e2e-overview") return route.fulfill({ json: boundaryOverview });
    if (pathname.endsWith("asr-segments.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "こんにちは" }] } });
    if (pathname.endsWith("subtitles.zh-ja.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "こんにちは", translated_text: "字幕" }] } });
    if (pathname.endsWith("highlight-candidates.json")) return route.fulfill({ json: { candidate_count: 0, candidates: [], no_candidates: "候補はありません" } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/workstation/tasks/task-e2e-overview");

  const heading = page.getByRole("heading", { name: title });
  const phrase = heading.locator(".ny-task-overview__title-phrase", { hasText: "の表示を確認する" });
  await expect(heading).toBeVisible();
  await expect(phrase).toHaveText("の表示を確認する");
  expect(await phrase.evaluate((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    return range.getClientRects().length;
  })).toBe(1);
  expect(await heading.locator(".ny-task-overview__title-phrase").allTextContents()).not.toContain("映像の字幕の確認の場面の");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.screenshot({ path: "/tmp/nyaru-japanese-title-evidence/task-overview-boundary-1280.png", fullPage: true });
});

test("starts a new title phrase after a split Japanese predicate", async ({ page }) => {
  const title = "映像の字幕レビューを確認して映像の場面";
  const predicateOverview = { ...taskOverview, title };
  await page.setViewportSize({ height: 900, width: 1280 });
  await page.route("http://127.0.0.1:8000/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v2/tasks/task-e2e-overview") return route.fulfill({ json: predicateOverview });
    if (pathname.endsWith("asr-segments.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "こんにちは" }] } });
    if (pathname.endsWith("subtitles.zh-ja.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "こんにちは", translated_text: "字幕" }] } });
    if (pathname.endsWith("highlight-candidates.json")) return route.fulfill({ json: { candidate_count: 0, candidates: [], no_candidates: "候補はありません" } });
    return route.fulfill({ json: {} });
  });

  await page.goto("/workstation/tasks/task-e2e-overview");

  const heading = page.getByRole("heading", { name: title });
  const predicatePhrase = heading.locator(".ny-task-overview__title-phrase", { hasText: "を確認して" });
  const followingPhrase = heading.locator(".ny-task-overview__title-phrase", { hasText: "映像の場面" });
  await expect(heading).toBeVisible();
  await expect(predicatePhrase).toHaveText("を確認して");
  await expect(followingPhrase).toHaveText("映像の場面");
  expect(await predicatePhrase.evaluate((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    return range.getClientRects().length;
  })).toBe(1);
  expect(await followingPhrase.evaluate((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    return range.getClientRects().length;
  })).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.screenshot({ path: "/tmp/nyaru-japanese-title-evidence/task-overview-predicate-1280.png", fullPage: true });
});

test("recovers a failed stage and exports a confirmed clip", async ({ page }) => {
  const taskId = "task-e2e-recovery";
  const recoveryOverview = {
    ...taskOverview,
    artifacts: [{ artifact_id: 7, created_at: "2026-07-12T03:00:00Z", kind: "highlight_candidates_json", metadata_json: "{}", path: `/api/tasks/${taskId}/artifacts/7/content/highlight-candidates.json`, stage_name: "highlight" }],
    artifact_readiness: [{ artifact_id: 7, kind: "highlight_candidates_json", path: `/api/tasks/${taskId}/artifacts/7/content/highlight-candidates.json`, stage_name: "highlight", status: "ready" }],
    current_stage: "translation",
    recovery_actions: [{ confirmation_required: false, description_key: "retry_stage", disabled_reason: null, enabled: true, endpoint: `/api/tasks/${taskId}/retry`, id: "retry_stage", label_key: "retry_stage", method: "POST", payload: { stage_name: "translation" }, success_behavior: "retry_stage" }],
    stages: taskOverview.stages.map((stage) => stage.name === "translation" ? { ...stage, failure_code: "translation_failed", status: "failed", summary: "翻译阶段需要恢复" } : stage),
    status: "failed",
    task_id: taskId,
    title: "失败恢复与导出验证",
  } as const;
  let retryBody: unknown;
  let exportBody: unknown;
  await page.route("http://127.0.0.1:8000/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === `/api/v2/tasks/${taskId}`) return route.fulfill({ json: recoveryOverview });
    if (pathname === `/api/tasks/${taskId}/retry`) {
      retryBody = request.postDataJSON();
      return route.fulfill({ json: { status: "accepted", task_id: taskId } });
    }
    if (pathname === `/api/tasks/${taskId}/clips`) {
      exportBody = request.postDataJSON();
      return route.fulfill({ json: { artifact_id: 44, candidate_id: 9, end_s: 18, filename: "clip-12-18.mp4", path: `/api/tasks/${taskId}/artifacts/44/content/clip-12-18.mp4`, start_s: 12 } });
    }
    if (pathname.endsWith("highlight-candidates.json")) return route.fulfill({ json: { candidate_count: 1, candidates: [{ candidate_id: 9, default_range: { end_s: 18, start_s: 12 }, end_s: 18, rank: 1, reasons: ["subtitle_density"], score: 0.91, start_s: 12 }] } });
    return route.fulfill({ json: {} });
  });

  await page.goto(`/workstation/tasks/${taskId}`);
  await expect(page.getByRole("heading", { name: "失败恢复与导出验证" })).toBeVisible();
  await expect(page.getByText("任务需要恢复")).toHaveCSS("white-space", "nowrap");
  await page.getByRole("button", { name: "从翻译重新尝试" }).click();
  await expect.poll(() => retryBody).toEqual({ stage_name: "translation" });
  await page.getByRole("button", { name: "确认导出" }).click();
  await expect.poll(() => exportBody).toEqual({ candidate_id: 9, end_s: 18, start_s: 12 });
  await expect(page.getByText("clip-12-18.mp4")).toBeVisible();
  await expect(page.getByRole("link", { name: "下载已导出片段" })).toHaveAttribute("href", /clip-12-18\.mp4$/);
});
