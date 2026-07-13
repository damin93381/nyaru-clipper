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
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v2/tasks/task-e2e-overview") return route.fulfill({ json: taskOverview });
    if (pathname.endsWith("asr-segments.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "你好" }] } });
    if (pathname.endsWith("subtitles.zh-ja.json")) return route.fulfill({ json: { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "你好", translated_text: "こんにちは" }] } });
    if (pathname.endsWith("highlight-candidates.json")) return route.fulfill({ json: { candidate_count: 0, candidates: [], no_candidates: "暂无高光候选" } });
    return route.fulfill({ json: {} });
  });

  await page.goto(`${process.env.WORKSTATION_E2E_BASE_URL ?? ""}/workstation/tasks/task-e2e-overview`);

  await expect(page.getByRole("heading", { name: "工作站任务概览验证" })).toBeVisible();
  await expect(page.getByText("校准字幕时间轴 · 4 / 5")).toBeVisible();
  await expect(page.getByRole("button", { name: /语音转写/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("complementary", { name: "上下文检查器" }).getByText("已写入可公开的转写进度摘要")).toBeVisible();
  await expect(page.getByText("你好")).toBeVisible();
  await expect(page.getByText("こんにちは")).toBeVisible();
  await page.screenshot({ path: "/tmp/nyaru-task13-evidence/overview-running.png", fullPage: true });

  await page.getByRole("button", { name: /翻译/ }).click();
  await expect(page).toHaveURL(/stage=translation$/);
  await expect(page.getByRole("complementary", { name: "上下文检查器" }).getByText("双语字幕数据")).toBeVisible();
  await page.screenshot({ path: "/tmp/nyaru-task13-evidence/overview-stage-selected.png", fullPage: true });
});
