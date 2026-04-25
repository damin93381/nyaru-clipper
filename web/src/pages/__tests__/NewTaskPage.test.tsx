import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { NewTaskPage } from "../NewTaskPage";
import { createTask } from "../../lib/api";

const mockNavigate = vi.fn();

vi.mock("../../lib/api", () => ({
  createTask: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");

  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NewTaskPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NewTaskPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the source input, submit action, and reserved option toggles", () => {
    renderPage();

    expect(screen.getByTestId("task-url-input")).toBeInTheDocument();
    expect(screen.getByTestId("task-submit-button")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /translation/i })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /highlight/i })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /export/i })).toBeInTheDocument();
  });

  it("submits a valid URL and navigates to the created task detail route", async () => {
    vi.mocked(createTask).mockResolvedValue({
      task_id: "task-created123",
      source_url: "https://www.bilibili.com/video/BV1xx411c7mD",
      normalized_source_url: "https://www.bilibili.com/video/BV1xx411c7mD",
      source_video_id: "BV1xx411c7mD",
      status: "pending",
      stages: [],
      created: true,
    });

    renderPage();

    fireEvent.change(screen.getByTestId("task-url-input"), {
      target: { value: "https://www.bilibili.com/video/BV1xx411c7mD" },
    });
    fireEvent.click(screen.getByTestId("task-submit-button"));

    await waitFor(() => {
      expect(createTask).toHaveBeenCalled();
    });

    expect(vi.mocked(createTask).mock.calls[0]?.[0]).toEqual({
      source_url: "https://www.bilibili.com/video/BV1xx411c7mD",
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/tasks/task-created123");
    });
  });
});
