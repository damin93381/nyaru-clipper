import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { downloadAsrModels, getTaskArtifacts, getTaskDetail, getTaskLogs, getTaskStages } from "../../lib/api";
import type {
  ArtifactRecord,
  AsrMissingModelRecovery,
  StageLogSummary,
  TaskDetail,
  TaskExecutionProgress,
  TaskStageRecord,
} from "../../lib/types";
import { getPollingInterval, TaskDetailPage } from "../TaskDetailPage";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
    return {
      ...actual,
      downloadAsrModels: vi.fn(),
      getTaskDetail: vi.fn(),
      getTaskStages: vi.fn(),
      getTaskArtifacts: vi.fn(),
    getTaskLogs: vi.fn(),
  };
});

const canonicalStages: TaskStageRecord[] = [
  { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
  { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
  { name: "asr", status: "success", summary: "Generated aligned transcript and Chinese subtitles", attempts: 1 },
  { name: "translation", status: "failed", summary: "translation_failed", attempts: 2 },
  { name: "highlight", status: "pending", summary: null, attempts: 0 },
  { name: "export", status: "pending", summary: null, attempts: 0 },
  { name: "report", status: "pending", summary: null, attempts: 0 },
];

const failureLogs: StageLogSummary[] = canonicalStages.map((stage) => ({
  stage_name: stage.name,
  status: stage.status,
  summary: stage.name === "translation" ? "translation_failed" : stage.summary,
  log_path: `/data/tasks/task-fixture123/logs/${stage.name}.log`,
}));

const artifacts: ArtifactRecord[] = [
  {
    id: 1,
    task_id: "task-fixture123",
    stage_name: "translation",
    kind: "bilingual_transcript_json",
    path: "/data/tasks/task-fixture123/work/subtitles.zh-ja.json",
    metadata_json: '{"model_metadata":{"provider":"hf","model_name":"fixture-translator"}}',
  },
];

interface TaskDetailWithAsrMissingModelRecovery extends TaskDetail {
  failure_recovery: AsrMissingModelRecovery;
}

interface TaskDetailWithExecutionProgress extends Omit<TaskDetail, "status"> {
  status: TaskDetail["status"] | "cancel_requested";
  execution_progress: TaskExecutionProgress;
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/tasks/task-fixture123"]}>
        <Routes>
          <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function mockTask(status: TaskDetail["status"]): TaskDetail {
  return {
    task_id: "task-fixture123",
    source_url: "https://www.bilibili.com/video/BV1fixture123",
    normalized_source_url: "https://www.bilibili.com/video/BV1fixture123",
    source_video_id: "BV1fixture123",
    status,
    stages: canonicalStages,
  };
}

function mockTaskWithAsrMissingModelRecovery(): TaskDetailWithAsrMissingModelRecovery {
  return {
    ...mockTask("failed"),
    stages: [
      { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
      { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
      { name: "asr", status: "failed", summary: "missing_model", attempts: 1 },
      { name: "translation", status: "pending", summary: null, attempts: 0 },
      { name: "highlight", status: "pending", summary: null, attempts: 0 },
      { name: "export", status: "pending", summary: null, attempts: 0 },
      { name: "report", status: "pending", summary: null, attempts: 0 },
    ],
    failure_recovery: {
      stage: "asr",
      kind: "missing_model",
      message: "ASR 缺少 WhisperX 模型文件。",
      models: [
        {
          key: "whisperx",
          label: "WhisperX 主模型",
          status: "missing",
          target_dir: "/models/whisperx/whisperx",
          repo_id: "large-v3",
          download_supported: true,
        },
        {
          key: "alignment",
          label: "Alignment 模型",
          status: "missing",
          target_dir: "/models/whisperx/alignment",
          repo_id: "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
          download_supported: true,
        },
      ],
    },
  };
}

function mockRunningAsrStages(): TaskStageRecord[] {
  return [
    { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
    { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
    { name: "asr", status: "running", summary: null, attempts: 1 },
    { name: "translation", status: "pending", summary: null, attempts: 0 },
    { name: "highlight", status: "pending", summary: null, attempts: 0 },
    { name: "export", status: "pending", summary: null, attempts: 0 },
    { name: "report", status: "pending", summary: null, attempts: 0 },
  ];
}

function mockTaskWithExecutionProgress(
  status: TaskDetailWithExecutionProgress["status"] = "running",
): TaskDetailWithExecutionProgress {
  return {
    task_id: "task-fixture123",
    source_url: "https://www.bilibili.com/video/BV1fixture123",
    normalized_source_url: "https://www.bilibili.com/video/BV1fixture123",
    source_video_id: "BV1fixture123",
    status,
    stages: mockRunningAsrStages(),
    execution_progress: {
      stage_name: "asr",
      current_phase: "transcribe",
      phase_index: 3,
      phase_count: 5,
      phase_started_at: "2026-05-03T05:00:00+00:00",
      heartbeat_at: "2026-05-03T05:01:00+00:00",
      latest_message: "transcribe running",
      phases: [
        { name: "model_load", status: "success", elapsed_ms: 1234 },
        { name: "vad", status: "success", elapsed_ms: 4567 },
        { name: "transcribe", status: "running", elapsed_ms: 8901 },
        { name: "align", status: "pending", elapsed_ms: null },
        { name: "persist", status: "pending", elapsed_ms: null },
      ],
    },
  };
}

function mockFailedTaskWithStaleExecutionProgress(): TaskDetail & {
  execution_progress: TaskExecutionProgress;
} {
  return {
    ...mockTask("failed"),
    stages: [
      { name: "ingest", status: "success", summary: "Downloaded source video via bbdown", attempts: 1 },
      { name: "media_prep", status: "success", summary: "Prepared ffprobe metadata and ASR wav", attempts: 1 },
      { name: "asr", status: "failed", summary: "malformed_progress_event", attempts: 1 },
      { name: "translation", status: "pending", summary: null, attempts: 0 },
      { name: "highlight", status: "pending", summary: null, attempts: 0 },
      { name: "export", status: "pending", summary: null, attempts: 0 },
      { name: "report", status: "pending", summary: null, attempts: 0 },
    ],
    execution_progress: {
      stage_name: "asr",
      current_phase: "transcribe",
      phase_index: 3,
      phase_count: 5,
      phase_started_at: "2026-05-03T05:00:00+00:00",
      heartbeat_at: "2026-05-03T05:01:00+00:00",
      latest_message: "stale progress should not render",
      phases: [
        { name: "model_load", status: "success", elapsed_ms: 1234 },
        { name: "vad", status: "success", elapsed_ms: 4567 },
        { name: "transcribe", status: "running", elapsed_ms: 8901 },
        { name: "align", status: "pending", elapsed_ms: null },
        { name: "persist", status: "pending", elapsed_ms: null },
      ],
    },
  };
}

describe("TaskDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    vi.mocked(downloadAsrModels).mockResolvedValue({ stage: "asr", kind: "missing_model", models: [] });
    vi.mocked(getTaskStages).mockResolvedValue(canonicalStages);
    vi.mocked(getTaskArtifacts).mockResolvedValue(artifacts);
    vi.mocked(getTaskLogs).mockResolvedValue(failureLogs);
  });

  it("renders the canonical stage timeline, readable failure summary, and artifact overview", async () => {
    vi.mocked(getTaskDetail).mockResolvedValue(mockTask("failed"));

    renderPage();

    expect(await screen.findByRole("heading", { name: "任务 task-fixture123" })).toBeInTheDocument();
    const failurePanel = screen.getByText("可读失败摘要").closest(".panel");
    expect(failurePanel).not.toBeNull();
    expect(within(failurePanel as HTMLElement).getByRole("heading", { name: "翻译阶段失败" })).toBeInTheDocument();
    expect(within(failurePanel as HTMLElement).getByText("翻译失败")).toBeInTheDocument();
    expect(
      screen.getByText("可从 翻译 重新尝试。上游已成功阶段保持不变，下游阶段继续等待。"),
    ).toBeInTheDocument();
    expect(screen.getByText("每 15 秒轮询")).toBeInTheDocument();
    expect(screen.getByText("Downloaded source video via bbdown")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "产物概览" })).toBeInTheDocument();
    expect(screen.getByText(/bilingual_transcript_json/i)).toBeInTheDocument();

    for (const stageName of [
      "采集",
      "媒体准备",
      "语音转写",
      "翻译",
      "高光",
      "导出",
      "报告",
    ]) {
      expect(screen.getByRole("heading", { level: 4, name: stageName })).toBeInTheDocument();
    }
  });

  it("renders inline ASR missing-model recovery guidance with download action and target directories", async () => {
    vi.mocked(getTaskDetail).mockResolvedValue(mockTaskWithAsrMissingModelRecovery());

    renderPage();

    expect(await screen.findByText("ASR 缺少 WhisperX 模型文件。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "自动下载缺失模型" })).toBeInTheDocument();
    expect(screen.getByText("/models/whisperx/whisperx")).toBeInTheDocument();
    expect(screen.getByText("/models/whisperx/alignment")).toBeInTheDocument();
  });

  it("requests automatic download for all missing ASR recovery models", async () => {
    vi.mocked(getTaskDetail).mockResolvedValue(mockTaskWithAsrMissingModelRecovery());

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "自动下载缺失模型" }));

    await waitFor(() => {
      expect(downloadAsrModels).toHaveBeenCalledWith("task-fixture123", ["whisperx", "alignment"]);
    });
  });

  it("renders an ASR execution progress section with current phase, timings, heartbeat, and latest message", async () => {
    vi.mocked(getTaskDetail).mockResolvedValue(mockTaskWithExecutionProgress("running"));
    vi.mocked(getTaskStages).mockResolvedValue(mockRunningAsrStages());
    vi.mocked(getTaskLogs).mockResolvedValue([]);

    renderPage();

    const progressPanel = (await screen.findByRole("heading", { name: "ASR 执行进度" })).closest(".panel");
    expect(progressPanel).not.toBeNull();
    expect(within(progressPanel as HTMLElement).getByText("语音转写（3 / 5）")).toBeInTheDocument();
    expect(within(progressPanel as HTMLElement).getByText("最近消息")).toBeInTheDocument();
    expect(within(progressPanel as HTMLElement).getByText("transcribe running")).toBeInTheDocument();
    expect(within(progressPanel as HTMLElement).getByText("最近心跳")).toBeInTheDocument();
    expect(within(progressPanel as HTMLElement).getByText("2026-05-03 05:01:00 UTC")).toBeInTheDocument();
    expect(within(progressPanel as HTMLElement).getByText("8.9s")).toBeInTheDocument();
    expect(within(progressPanel as HTMLElement).getByText("1.2s")).toBeInTheDocument();
  });

  it("shows explicit cancel-requested waiting copy for active ASR instead of an idle summary", async () => {
    vi.mocked(getTaskDetail).mockResolvedValue(mockTaskWithExecutionProgress("cancel_requested"));
    vi.mocked(getTaskStages).mockResolvedValue(mockRunningAsrStages());
    vi.mocked(getTaskLogs).mockResolvedValue([]);

    renderPage();

    await screen.findByRole("heading", { name: "ASR 执行进度" });
    const timelinePanel = screen.getByRole("heading", { name: "阶段时间线" }).closest(".panel");
    expect(timelinePanel).not.toBeNull();
    const asrCard = within(timelinePanel as HTMLElement)
      .getByRole("heading", { level: 4, name: "语音转写" })
      .closest(".stage-card");
    expect(asrCard).not.toBeNull();
    expect(within(asrCard as HTMLElement).getByText("已请求取消，正在等待当前 ASR 执行停止。"))
      .toBeInTheDocument();
    expect(within(asrCard as HTMLElement).queryByText("等待该阶段开始。"))
      .not.toBeInTheDocument();
  });

  it("does not render active ASR progress for a terminal task even if stale execution_progress is still present", async () => {
    const failedTask = mockFailedTaskWithStaleExecutionProgress();
    const failedLogs: StageLogSummary[] = failedTask.stages.map((stage) => ({
      stage_name: stage.name,
      status: stage.status,
      summary: stage.summary,
      log_path: `/data/tasks/task-fixture123/logs/${stage.name}.log`,
    }));

    vi.mocked(getTaskDetail).mockResolvedValue(failedTask);
    vi.mocked(getTaskStages).mockResolvedValue(failedTask.stages);
    vi.mocked(getTaskLogs).mockResolvedValue(failedLogs);

    renderPage();

    expect(await screen.findByRole("heading", { name: "任务 task-fixture123" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "ASR 执行进度" })).not.toBeInTheDocument();
    expect(screen.queryByText("stale progress should not render")).not.toBeInTheDocument();

    const failurePanel = screen.getByText("可读失败摘要").closest(".panel");
    expect(failurePanel).not.toBeNull();
    expect(within(failurePanel as HTMLElement).getByRole("heading", { name: "语音转写阶段失败" }))
      .toBeInTheDocument();
  });

  it("uses a 3-second polling cadence for non-terminal task states", () => {
    expect(getPollingInterval("pending")).toBe(3_000);
    expect(getPollingInterval("running")).toBe(3_000);
  });

  it("renders cancelled as a terminal task status with the slower polling cadence", async () => {
    vi.mocked(getTaskDetail).mockResolvedValue(mockTask("cancelled"));

    renderPage();

    expect(await screen.findByRole("heading", { name: "任务 task-fixture123" })).toBeInTheDocument();
    expect(screen.getByText("已取消")).toBeInTheDocument();
    expect(getPollingInterval("cancelled")).toBe(15_000);
  });

  it("uses a 15-second polling cadence after terminal task states", () => {
    expect(getPollingInterval("success")).toBe(15_000);
    expect(getPollingInterval("failed")).toBe(15_000);
    expect(getPollingInterval("cancelled")).toBe(15_000);
    expect(getPollingInterval("skipped")).toBe(15_000);
  });
});
