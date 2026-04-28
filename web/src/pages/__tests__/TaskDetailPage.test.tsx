import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { TaskDetailPage, getPollingInterval } from "../TaskDetailPage";
import {
  downloadAsrModels,
  getTaskArtifacts,
  getTaskDetail,
  getTaskLogs,
  getTaskStages,
} from "../../lib/api";
import type {
  ArtifactRecord,
  StageLogSummary,
  TaskDetail,
  TaskStageRecord,
} from "../../lib/types";

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

function mockTaskWithAsrMissingModelRecovery(): TaskDetail {
  return {
    ...mockTask("failed"),
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

describe("TaskDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    vi.mocked(downloadAsrModels).mockResolvedValue({
      stage: "asr",
      kind: "missing_model",
      models: [],
    });
    vi.mocked(getTaskStages).mockResolvedValue(canonicalStages);
    vi.mocked(getTaskArtifacts).mockResolvedValue(artifacts);
    vi.mocked(getTaskLogs).mockResolvedValue(failureLogs);
  });

  it("renders the canonical stage timeline, readable failure summary, and artifact overview", async () => {
    vi.mocked(getTaskDetail).mockResolvedValue(mockTask("failed"));

    renderPage();

    expect(await screen.findByRole("heading", { name: /task task-fixture123/i })).toBeInTheDocument();
    expect(screen.getByText(/translation stage failed/i)).toBeInTheDocument();
    expect(screen.getByText(/retry-ready from translation/i)).toBeInTheDocument();
    expect(screen.getByText(/bilingual_transcript_json/i)).toBeInTheDocument();

    for (const stageName of [
      "ingest",
      "media_prep",
      "asr",
      "translation",
      "highlight",
      "export",
      "report",
    ]) {
      expect(screen.getByRole("heading", { level: 4, name: new RegExp(stageName, "i") })).toBeInTheDocument();
    }
  });

  it("renders inline ASR missing-model recovery guidance with download action and target directories", async () => {
    vi.mocked(getTaskDetail).mockResolvedValue(mockTaskWithAsrMissingModelRecovery());

    renderPage();

    expect(await screen.findByText("ASR 缺少 WhisperX 模型文件。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download missing ASR models" })).toBeInTheDocument();
    expect(screen.getByText("/models/whisperx/whisperx")).toBeInTheDocument();
    expect(screen.getByText("/models/whisperx/alignment")).toBeInTheDocument();
  });

  it("requests automatic download for all missing ASR recovery models", async () => {
    vi.mocked(getTaskDetail).mockResolvedValue(mockTaskWithAsrMissingModelRecovery());

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Download missing ASR models" }));

    await waitFor(() => {
      expect(downloadAsrModels).toHaveBeenCalledWith("task-fixture123", ["whisperx", "alignment"]);
    });
  });

  it("uses a 3-second polling cadence for non-terminal task states", () => {
    expect(getPollingInterval("pending")).toBe(3_000);
    expect(getPollingInterval("running")).toBe(3_000);
  });

  it("uses a 15-second polling cadence after terminal task states", () => {
    expect(getPollingInterval("success")).toBe(15_000);
    expect(getPollingInterval("failed")).toBe(15_000);
    expect(getPollingInterval("skipped")).toBe(15_000);
  });
});
