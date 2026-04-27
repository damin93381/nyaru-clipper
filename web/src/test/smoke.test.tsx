import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { getRuntimeCapabilities } from "../lib/api";
import type { RuntimeCapabilities } from "../lib/types";
import { NewTaskPage } from "../pages/NewTaskPage";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    getRuntimeCapabilities: vi.fn(),
  };
});

const warningCapabilities: RuntimeCapabilities = {
  status: "warning",
  detected_profile: "cpu-only",
  platform: {
    is_wsl: false,
    machine: "x86_64",
    release: "6.8.0-generic",
    system: "linux",
    version: "#1 SMP PREEMPT_DYNAMIC",
  },
  accelerator: {
    available: false,
    backend: "cpu",
    cuda_version: null,
    device_count: 0,
    device_name: null,
    hip_version: null,
    kind: "cpu",
    torch_available: true,
    torch_build_family: "cpu",
    torch_version: "2.6.0",
  },
  dependencies: {
    tools: {},
    python: {},
  },
  issues: [],
  warnings: ["GPU runtime was not detected; backend is operating in cpu-only mode."],
};


describe("workspace smoke", () => {
  function renderShell() {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          refetchOnWindowFocus: false,
        },
      },
    });

    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<NewTaskPage />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the bootstrap shell alongside warning-only environment status", async () => {
    vi.mocked(getRuntimeCapabilities).mockResolvedValue(warningCapabilities);

    renderShell();

    expect(await screen.findByRole("heading", { name: "Bilibili VTuber 工作台" })).toBeInTheDocument();
    expect(await screen.findByTestId("environment-status-card")).toBeInTheDocument();
    expect(await screen.findByText(/gpu runtime was not detected/i)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "将 Bilibili 录播加入标准工作流水线" }),
    ).toBeInTheDocument();
  });

  it("keeps the main task view available when capability fetching fails", async () => {
    vi.mocked(getRuntimeCapabilities).mockRejectedValue(new Error("runtime endpoint unavailable"));

    renderShell();

    expect(await screen.findByRole("heading", { name: "Bilibili VTuber 工作台" })).toBeInTheDocument();
    expect(await screen.findByTestId("environment-status-card")).toBeInTheDocument();
    expect(
      await screen.findByText("运行能力检查暂时不可用。任务界面仍可继续使用，系统稍后会再次重试。"),
    ).toBeInTheDocument();
    expect(await screen.findByText("runtime endpoint unavailable")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "将 Bilibili 录播加入标准工作流水线" }),
    ).toBeInTheDocument();
  });
});
