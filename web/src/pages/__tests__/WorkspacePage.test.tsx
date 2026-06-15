import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";

import { exportTaskClip, fetchArtifactJson } from "../../lib/api";
import type { ArtifactRecord } from "../../lib/types";
import { WorkspacePage } from "../WorkspacePage";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    exportTaskClip: vi.fn(),
    fetchArtifactJson: vi.fn(),
  };
});

type WorkspacePageProps = ComponentProps<typeof WorkspacePage>;

function renderPage(
  artifacts: ArtifactRecord[],
  props: Partial<Pick<WorkspacePageProps, "artifactReadiness">> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <WorkspacePage artifacts={artifacts} taskId="task-workspace123" {...props} />
    </QueryClientProvider>,
  );
}

const baseArtifacts: ArtifactRecord[] = [
  {
    id: 1,
    task_id: "task-workspace123",
    stage_name: "asr",
    kind: "transcript_json",
    path: "/api/tasks/task-workspace123/artifacts/1/content/asr-segments.json",
    metadata_json: "{}",
  },
  {
    id: 2,
    task_id: "task-workspace123",
    stage_name: "translation",
    kind: "bilingual_transcript_json",
    path: "/api/tasks/task-workspace123/artifacts/2/content/subtitles.zh-ja.json",
    metadata_json: '{"segment_count":2}',
  },
  {
    id: 3,
    task_id: "task-workspace123",
    stage_name: "translation",
    kind: "bilingual_subtitle_srt",
    path: "/api/tasks/task-workspace123/artifacts/3/content/subtitles.zh-ja.srt",
    metadata_json: "{}",
  },
  {
    id: 4,
    task_id: "task-workspace123",
    stage_name: "highlight",
    kind: "highlight_candidates_json",
    path: "/api/tasks/task-workspace123/artifacts/4/content/highlight-candidates.json",
    metadata_json: '{"candidate_count":1}',
  },
  {
    id: 5,
    task_id: "task-workspace123",
    stage_name: "report",
    kind: "task_report_markdown",
    path: "/api/tasks/task-workspace123/artifacts/5/content/task-report.md",
    metadata_json: "{}",
  },
];

describe("WorkspacePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders side-by-side subtitle rows, ranked candidates, and exported clip downloads", async () => {
    vi.mocked(fetchArtifactJson).mockImplementation(async (path: string) => {
      if (path.includes("asr-segments")) {
        return {
          segments: [
            { id: "seg-0001", start_seconds: 0, end_seconds: 1.4, text: "你好" },
            { id: "seg-0002", start_seconds: 1.4, end_seconds: 3, text: "世界" },
          ],
        };
      }

      if (path.includes("subtitles.zh-ja")) {
        return {
          segments: [
            { id: "seg-0001", start_seconds: 0, end_seconds: 1.4, text: "你好", translated_text: "こんにちは" },
            { id: "seg-0002", start_seconds: 1.4, end_seconds: 3, text: "世界", translated_text: "世界" },
          ],
        };
      }

      return {
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
      };
    });

    vi.mocked(exportTaskClip).mockResolvedValue({
      task_id: "task-workspace123",
      candidate_id: 41,
      start_s: 15.5,
      end_s: 45,
      path: "/api/tasks/task-workspace123/artifacts/99/content/clip-00015500-00045000.mp4",
      filename: "clip-00015500-00045000.mp4",
      artifact_id: 99,
    });

    renderPage(baseArtifacts);

    expect(await screen.findByRole("heading", { name: "字幕审阅与高光确认" })).toBeInTheDocument();
    expect(screen.getByText("任务 task-workspace123 工作区")).toBeInTheDocument();
    expect(await screen.findByText(/seg-0001/i)).toBeInTheDocument();
    expect(screen.getByText("你好")).toBeInTheDocument();
    expect(screen.getByText("こんにちは")).toBeInTheDocument();
    expect(screen.getByText(/笑声片段/i)).toBeInTheDocument();
    expect(screen.getByText(/强调标点/i)).toBeInTheDocument();
    expect(screen.getByText("开始（秒）")).toBeInTheDocument();
    expect(screen.getByText("结束（秒）")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认导出" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^下载双语字幕$/ })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/api/tasks/task-workspace123/artifacts/3/content/subtitles.zh-ja.srt",
    );
    expect(screen.getByRole("link", { name: /下载任务报告/i })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/api/tasks/task-workspace123/artifacts/5/content/task-report.md",
    );

    const startInput = screen.getByTestId("candidate-start-input");
    const endInput = screen.getByTestId("candidate-end-input");

    expect(startInput).toHaveValue(16);
    expect(endInput).toHaveValue(44);

    fireEvent.change(startInput, { target: { value: "15.5" } });
    fireEvent.change(endInput, { target: { value: "45" } });
    fireEvent.click(screen.getByTestId("candidate-confirm-button"));

    await waitFor(() => {
      expect(exportTaskClip).toHaveBeenCalledWith("task-workspace123", {
        candidate_id: 41,
        start_s: 15.5,
        end_s: 45,
      });
    });

    expect(await screen.findByText(/clip-00015500-00045000\.mp4/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载已导出片段" })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/api/tasks/task-workspace123/artifacts/99/content/clip-00015500-00045000.mp4",
    );
  });

  it("keeps zero-candidate messaging and subtitle/report downloads visible", async () => {
    vi.mocked(fetchArtifactJson).mockImplementation(async (path: string) => {
      if (path.includes("asr-segments")) {
        return {
          segments: [{ id: "seg-0007", start_seconds: 24, end_seconds: 28, text: "然后慢慢看下一个部分。" }],
        };
      }

      if (path.includes("subtitles.zh-ja")) {
        return {
          segments: [
            {
              id: "seg-0007",
              start_seconds: 24,
              end_seconds: 28,
              text: "然后慢慢看下一个部分。",
              translated_text: "それから次の部分をゆっくり見ます。",
            },
          ],
        };
      }

      return {
        candidate_count: 0,
        no_candidates: "No highlight candidates cleared the minimum score threshold from the available scene and subtitle signals.",
        candidates: [],
      };
    });

    renderPage(baseArtifacts);

    expect(await screen.findByText("暂无可用高光候选")).toBeInTheDocument();
    expect(
      await screen.findByText(/no highlight candidates cleared the minimum score threshold/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("candidate-confirm-button")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^下载双语字幕$/ })).toBeVisible();
    expect(screen.getByRole("link", { name: "下载任务报告" })).toBeVisible();
  });

  it("distinguishes artifact load errors from truly empty workspace data", async () => {
    vi.mocked(fetchArtifactJson).mockRejectedValue(new Error("network down"));

    const firstRender = renderPage(baseArtifacts);

    expect(await screen.findAllByText("加载工作台数据失败")).not.toHaveLength(0);
    expect(screen.getAllByRole("button", { name: "重新加载此区域" })[0]).toBeVisible();
    expect(screen.queryByText("暂无数据")).not.toBeInTheDocument();

    firstRender.unmount();

    vi.clearAllMocks();
    vi.mocked(fetchArtifactJson).mockImplementation(async (path: string) => {
      if (path.includes("highlight-candidates")) {
        return {
          candidate_count: undefined,
          no_candidates: null,
          candidates: [],
        };
      }

      return { segments: [] };
    });

    renderPage(baseArtifacts);

    expect(await screen.findAllByText("暂无数据")).toHaveLength(2);
    expect(screen.queryByText("加载工作台数据失败")).not.toBeInTheDocument();
  });

  it("shows backend artifact readiness states before treating sections as empty", () => {
    renderPage([], {
      artifactReadiness: [
        {
          kind: "transcript_json",
          stage_name: "asr",
          status: "not_ready",
          artifact_id: null,
          path: null,
        },
        {
          kind: "highlight_candidates",
          stage_name: "highlight",
          status: "missing",
          artifact_id: null,
          path: null,
        },
      ],
    });

    expect(screen.getByText("该数据尚未生成")).toBeInTheDocument();
    expect(screen.getByText("产物缺失，可重试生成阶段")).toBeInTheDocument();
    expect(screen.queryByText("暂无数据")).not.toBeInTheDocument();
  });

  it("blocks invalid export ranges before calling the backend", async () => {
    vi.mocked(fetchArtifactJson).mockImplementation(async (path: string) => {
      if (path.includes("highlight-candidates")) {
        return {
          candidate_count: 1,
          no_candidates: null,
          candidates: [
            {
              candidate_id: 41,
              rank: 1,
              start_s: 18,
              end_s: 42,
              score: 0.91,
              reasons: [],
              default_range: { start_s: 16, end_s: 44 },
            },
          ],
        };
      }

      return { segments: [] };
    });

    renderPage(baseArtifacts);

    const startInput = await screen.findByTestId("candidate-start-input");
    const endInput = screen.getByTestId("candidate-end-input");

    fireEvent.change(startInput, { target: { value: "45" } });
    fireEvent.change(endInput, { target: { value: "45" } });
    fireEvent.click(screen.getByTestId("candidate-confirm-button"));

    expect(await screen.findByText("开始时间必须早于结束时间")).toBeInTheDocument();
    expect(exportTaskClip).not.toHaveBeenCalled();
    expect(startInput).toHaveValue(45);
    expect(endInput).toHaveValue(45);

    fireEvent.change(startInput, { target: { value: "-1" } });
    fireEvent.change(endInput, { target: { value: "3" } });
    fireEvent.click(screen.getByTestId("candidate-confirm-button"));

    expect(await screen.findByText("时间不能小于 0 秒")).toBeInTheDocument();
    expect(exportTaskClip).not.toHaveBeenCalled();
    expect(startInput).toHaveValue(-1);
    expect(endInput).toHaveValue(3);
  });

  it("surfaces backend export errors without clearing edited clip times", async () => {
    vi.mocked(fetchArtifactJson).mockImplementation(async (path: string) => {
      if (path.includes("highlight-candidates")) {
        return {
          candidate_count: 1,
          no_candidates: null,
          candidates: [
            {
              candidate_id: 41,
              rank: 1,
              start_s: 18,
              end_s: 42,
              score: 0.91,
              reasons: [],
              default_range: { start_s: 16, end_s: 44 },
            },
          ],
        };
      }

      return { segments: [] };
    });
    vi.mocked(exportTaskClip).mockRejectedValue(new Error("outside the source duration"));

    renderPage(baseArtifacts);

    const startInput = await screen.findByTestId("candidate-start-input");
    const endInput = screen.getByTestId("candidate-end-input");
    fireEvent.change(startInput, { target: { value: "12" } });
    fireEvent.change(endInput, { target: { value: "120" } });
    fireEvent.click(screen.getByTestId("candidate-confirm-button"));

    expect(await screen.findByText("outside the source duration")).toBeInTheDocument();
    expect(startInput).toHaveValue(12);
    expect(endInput).toHaveValue(120);
  });
});
