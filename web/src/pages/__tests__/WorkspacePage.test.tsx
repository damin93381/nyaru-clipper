import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { WorkspacePage } from "../WorkspacePage";
import { exportTaskClip, fetchArtifactJson } from "../../lib/api";
import type { ArtifactRecord } from "../../lib/types";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    exportTaskClip: vi.fn(),
    fetchArtifactJson: vi.fn(),
  };
});

function renderPage(artifacts: ArtifactRecord[]) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <WorkspacePage artifacts={artifacts} taskId="task-workspace123" />
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

    expect(await screen.findByText(/seg-0001/i)).toBeInTheDocument();
    expect(screen.getByText("你好")).toBeInTheDocument();
    expect(screen.getByText("こんにちは")).toBeInTheDocument();
    expect(screen.getByText(/laughter phrase/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download bilingual subtitles/i })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/api/tasks/task-workspace123/artifacts/3/content/subtitles.zh-ja.srt",
    );
    expect(screen.getByRole("link", { name: /download task report/i })).toHaveAttribute(
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
    expect(screen.getByRole("link", { name: /download exported clip/i })).toHaveAttribute(
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

    expect(
      await screen.findByText(/no highlight candidates cleared the minimum score threshold/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("candidate-confirm-button")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download bilingual subtitles/i })).toBeVisible();
    expect(screen.getByRole("link", { name: /download task report/i })).toBeVisible();
  });
});
