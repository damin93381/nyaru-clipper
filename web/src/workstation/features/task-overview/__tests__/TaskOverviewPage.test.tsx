import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWorkstation } from "../../../testing/renderWorkstation";

vi.mock("../api", () => ({
  getWorkstationTaskOverview: vi.fn(),
}));

vi.mock("../../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../lib/api")>();
  return {
    ...actual,
    downloadAsrModels: vi.fn(),
    exportTaskClip: vi.fn(),
    fetchArtifactJson: vi.fn(),
    retryTaskFromStage: vi.fn(),
  };
});

import { downloadAsrModels, exportTaskClip, fetchArtifactJson, retryTaskFromStage } from "../../../../lib/api";
import { getWorkstationTaskOverview } from "../api";
import { TaskOverviewPage } from "../TaskOverviewPage";
import type { WorkstationTaskOverview } from "../api";
import { TaskOverviewInspector } from "../TaskOverviewInspector";

const overview = {
  archived_at: null,
  artifact_readiness: [
    { artifact_id: 1, kind: "transcript_json", path: "/api/tasks/task-overview/artifacts/1/content/asr-segments.json", stage_name: "asr", status: "ready" },
    { artifact_id: 2, kind: "bilingual_transcript_json", path: "/api/tasks/task-overview/artifacts/2/content/subtitles.zh-ja.json", stage_name: "translation", status: "ready" },
    { artifact_id: 3, kind: "highlight_candidates_json", path: "/api/tasks/task-overview/artifacts/3/content/highlight-candidates.json", stage_name: "highlight", status: "ready" },
  ],
  artifacts: [
    { artifact_id: 1, created_at: "2026-07-12T03:00:00Z", kind: "transcript_json", metadata_json: "{}", path: "/api/tasks/task-overview/artifacts/1/content/asr-segments.json", stage_name: "asr" },
    { artifact_id: 2, created_at: "2026-07-12T03:00:00Z", kind: "bilingual_transcript_json", metadata_json: "{}", path: "/api/tasks/task-overview/artifacts/2/content/subtitles.zh-ja.json", stage_name: "translation" },
    { artifact_id: 3, created_at: "2026-07-12T03:00:00Z", kind: "highlight_candidates_json", metadata_json: "{}", path: "/api/tasks/task-overview/artifacts/3/content/highlight-candidates.json", stage_name: "highlight" },
  ],
  created_at: "2026-07-12T03:00:00Z",
  current_stage: "asr",
  execution_progress: { current_phase: "align", heartbeat_at: "2026-07-12T03:03:00Z", latest_message: "正在校准字幕时间轴", phase_count: 5, phase_index: 4, phase_started_at: "2026-07-12T03:02:00Z", phases: [], stage_name: "asr" },
  pipeline_run_id: "run-1",
  progress_percent: 58,
  recovery_actions: [],
  safe_logs: [{ display_label: "ASR 转写", stage_name: "asr", status: "running", summary: "已写入可公开的转写进度摘要" }],
  source_kind: "bilibili",
  source_label: "夏日直播回放",
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
  task_id: "task-overview",
  title: "夏日回放字幕审阅",
  updated_at: "2026-07-12T03:03:00Z",
} satisfies WorkstationTaskOverview;

function renderOverview() {
  return renderWorkstation(<TaskOverviewPage taskId="task-overview" />);
}

describe("TaskOverviewPage", () => {
  afterEach(() => vi.clearAllMocks());

  it("renders seven pipeline stages, active ASR progress, safe log summaries, artifact rows, and subtitle review", async () => {
    vi.mocked(getWorkstationTaskOverview).mockResolvedValue(overview);
    vi.mocked(fetchArtifactJson).mockImplementation(async (path: string) => {
      if (path.includes("asr-segments")) return { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "你好" }] };
      if (path.includes("subtitles")) return { segments: [{ id: "seg-0001", start_seconds: 0, end_seconds: 1.5, text: "你好", translated_text: "こんにちは" }] };
      return { candidate_count: 0, candidates: [], no_candidates: "暂无高光候选" };
    });

    renderOverview();

    expect(await screen.findByRole("heading", { name: "夏日回放字幕审阅" })).toBeVisible();
    expect(screen.getByText("夏日直播回放")).toBeVisible();
    expect(screen.getByRole("list", { name: "任务阶段" })).toHaveTextContent(/采集.*媒体准备.*语音转写.*翻译.*高光.*导出.*报告/);
    expect(screen.getByRole("button", { name: /媒体准备/ }).querySelector(".ny-progress__stage-label")).toHaveTextContent("媒体准备");
    expect(screen.getByRole("button", { name: /语音转写/ }).querySelector(".ny-progress__stage-label")).toHaveTextContent("语音转写");
    expect(screen.getByText("校准字幕时间轴 · 4 / 5")).toBeVisible();
    expect(screen.getByText("正在校准字幕时间轴")).toBeVisible();
    expect(screen.queryByText(/\/data\//)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /语音转写/ })).toBeVisible();
    expect(await screen.findByText("你好")).toBeVisible();
    expect(screen.getByText("こんにちは")).toBeVisible();
    expect(screen.getByRole("region", { name: "字幕表格，可横向滚动" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByText("暂无可用高光候选")).toBeVisible();
  });

  it.each<["pending" | "success" | "cancelled", string, WorkstationTaskOverview["recovery_actions"]]>([
    ["pending", "等待开始", []],
    ["success", "任务已完成", []],
    ["cancelled", "任务已取消", []],
  ])("renders the %s lifecycle state", async (status, label, recoveryActions) => {
    vi.mocked(getWorkstationTaskOverview).mockResolvedValue({ ...overview, current_stage: null, execution_progress: null, recovery_actions: recoveryActions, status });
    renderOverview();
    expect(await screen.findByText(label)).toBeVisible();
  });

  it("downloads missing models then retries the trusted ASR stage", async () => {
    vi.mocked(getWorkstationTaskOverview).mockResolvedValue({
      ...overview,
      current_stage: "asr",
      recovery_actions: [
        { confirmation_required: false, description_key: "download_asr_model", disabled_reason: null, enabled: true, endpoint: "/api/tasks/task-overview/asr/models/download", id: "download_asr_model", label_key: "download_asr_model", method: "POST", payload: { model_keys: ["whisperx", "alignment"] }, success_behavior: "retry_stage_after_success" },
        { confirmation_required: false, description_key: "retry_stage", disabled_reason: null, enabled: true, endpoint: "/api/tasks/task-overview/retry", id: "retry_stage", label_key: "retry_stage", method: "POST", payload: { stage_name: "asr" }, success_behavior: "poll_task" },
      ],
      status: "failed",
    });
    renderOverview();
    fireEvent.click(await screen.findByRole("button", { name: "下载缺失模型" }));
    await waitFor(() => expect(downloadAsrModels).toHaveBeenCalledWith("task-overview", ["whisperx", "alignment"]));
    await waitFor(() => expect(retryTaskFromStage).toHaveBeenCalledWith("task-overview", "asr"));
    expect(vi.mocked(downloadAsrModels).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(retryTaskFromStage).mock.invocationCallOrder[0]);
  });

  it("shows a recovery failure when the post-download ASR retry is rejected", async () => {
    vi.mocked(getWorkstationTaskOverview).mockResolvedValue({
      ...overview,
      current_stage: "asr",
      recovery_actions: [{ confirmation_required: false, description_key: "download_asr_model", disabled_reason: null, enabled: true, endpoint: "/api/tasks/task-overview/asr/models/download", id: "download_asr_model", label_key: "download_asr_model", method: "POST", payload: { model_keys: ["whisperx"] }, success_behavior: "retry_stage_after_success" }],
      status: "failed",
    });
    vi.mocked(retryTaskFromStage).mockRejectedValueOnce(new Error("ASR 重试请求失败"));
    renderOverview();
    fireEvent.click(await screen.findByRole("button", { name: "下载缺失模型" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("恢复操作没有完成，请检查安全日志后重试。");
    expect(retryTaskFromStage).toHaveBeenCalledWith("task-overview", "asr");
  });

  it("disables the model download while a manual stage retry is pending", async () => {
    let resolveRetry: (() => void) | undefined;
    vi.mocked(getWorkstationTaskOverview).mockResolvedValue({
      ...overview,
      current_stage: "asr",
      recovery_actions: [
        { confirmation_required: false, description_key: "download_asr_model", disabled_reason: null, enabled: true, endpoint: "/api/tasks/task-overview/asr/models/download", id: "download_asr_model", label_key: "download_asr_model", method: "POST", payload: { model_keys: ["whisperx"] }, success_behavior: "retry_stage_after_success" },
        { confirmation_required: false, description_key: "retry_stage", disabled_reason: null, enabled: true, endpoint: "/api/tasks/task-overview/retry", id: "retry_stage", label_key: "retry_stage", method: "POST", payload: { stage_name: "asr" }, success_behavior: "poll_task" },
      ],
      status: "failed",
    });
    vi.mocked(retryTaskFromStage).mockImplementationOnce(() => new Promise((resolve) => { resolveRetry = () => resolve({ retry_stage: "asr", status: "pending", task_id: "task-overview" }); }));
    renderOverview();
    fireEvent.click(await screen.findByRole("button", { name: "从语音转写重新尝试" }));
    await waitFor(() => expect(retryTaskFromStage).toHaveBeenCalledWith("task-overview", "asr"));
    expect(screen.getByRole("button", { name: "下载缺失模型" })).toBeDisabled();
    resolveRetry?.();
  });

  it("disables manual retry while the model download sequence is pending", async () => {
    let resolveDownload: (() => void) | undefined;
    vi.mocked(getWorkstationTaskOverview).mockResolvedValue({
      ...overview,
      current_stage: "asr",
      recovery_actions: [
        { confirmation_required: false, description_key: "download_asr_model", disabled_reason: null, enabled: true, endpoint: "/api/tasks/task-overview/asr/models/download", id: "download_asr_model", label_key: "download_asr_model", method: "POST", payload: { model_keys: ["whisperx"] }, success_behavior: "retry_stage_after_success" },
        { confirmation_required: false, description_key: "retry_stage", disabled_reason: null, enabled: true, endpoint: "/api/tasks/task-overview/retry", id: "retry_stage", label_key: "retry_stage", method: "POST", payload: { stage_name: "asr" }, success_behavior: "poll_task" },
      ],
      status: "failed",
    });
    vi.mocked(downloadAsrModels).mockImplementationOnce(() => new Promise((resolve) => { resolveDownload = () => resolve({ kind: "missing_model", models: [], stage: "asr" }); }));
    renderOverview();
    fireEvent.click(await screen.findByRole("button", { name: "下载缺失模型" }));
    await waitFor(() => expect(downloadAsrModels).toHaveBeenCalledWith("task-overview", ["whisperx"]));
    expect(screen.getByRole("button", { name: "从语音转写重新尝试" })).toBeDisabled();
    resolveDownload?.();
    await waitFor(() => expect(retryTaskFromStage).toHaveBeenCalledWith("task-overview", "asr"));
  });

  it("keeps edited export input after a failed clip request and adds the download after success", async () => {
    vi.mocked(getWorkstationTaskOverview).mockResolvedValue(overview);
    vi.mocked(fetchArtifactJson).mockImplementation(async (path: string) => path.includes("highlight")
      ? { candidate_count: 1, candidates: [{ candidate_id: 8, default_range: { end_s: 44, start_s: 16 }, end_s: 42, rank: 1, reasons: [], score: 0.9, start_s: 18 }], no_candidates: null }
      : { segments: [] });
    vi.mocked(exportTaskClip).mockRejectedValueOnce(new Error("片段超出视频时长")).mockResolvedValueOnce({ artifact_id: 9, candidate_id: 8, filename: "clip.mp4", path: "/api/tasks/task-overview/artifacts/9/content/clip.mp4", end_s: 45, start_s: 15, task_id: "task-overview" });
    renderOverview();
    const start = await screen.findByTestId("candidate-start-input");
    const end = screen.getByTestId("candidate-end-input");
    fireEvent.change(start, { target: { value: "15" } });
    fireEvent.change(end, { target: { value: "45" } });
    fireEvent.click(screen.getByTestId("candidate-confirm-button"));
    expect(await screen.findByText("片段超出视频时长")).toBeVisible();
    expect(start).toHaveValue(15);
    expect(end).toHaveValue(45);
    fireEvent.click(screen.getByTestId("candidate-confirm-button"));
    expect(await screen.findByRole("link", { name: "下载已导出片段" })).toHaveAttribute("href", "http://127.0.0.1:8000/api/tasks/task-overview/artifacts/9/content/clip.mp4");
  });

  it("limits the persistent inspector to selected-stage safe summaries and keeps artifact paths in technical disclosure", () => {
    renderWorkstation(<TaskOverviewInspector selectedStage="asr" task={overview} />);
    expect(screen.getByText("已写入可公开的转写进度摘要")).toBeVisible();
    expect(screen.queryByText("/data/tasks/task-overview/logs/asr.log")).not.toBeInTheDocument();
    expect(screen.getByText("转写片段")).toBeVisible();
    expect(screen.getByText("技术信息")).toBeVisible();
  });
});
