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
    hip_version: null,
    kind: "cpu",
    torch_available: true,
    torch_version: "2.6.0",
  },
  dependencies: {
    tools: {},
    python: {},
  },
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

    expect(await screen.findByRole("heading", { name: /bilibili vtuber suite/i })).toBeInTheDocument();
    expect(await screen.findByTestId("environment-status-card")).toBeInTheDocument();
    expect(await screen.findByText(/gpu runtime was not detected/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /queue a bilibili vod for the canonical workstation pipeline/i })).toBeInTheDocument();
  });

  it("keeps the main task view available when capability fetching fails", async () => {
    vi.mocked(getRuntimeCapabilities).mockRejectedValue(new Error("runtime endpoint unavailable"));

    renderShell();

    expect(await screen.findByRole("heading", { name: /bilibili vtuber suite/i })).toBeInTheDocument();
    expect(await screen.findByTestId("environment-status-card")).toBeInTheDocument();
    expect(await screen.findByText(/runtime capability checks are temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /queue a bilibili vod for the canonical workstation pipeline/i })).toBeInTheDocument();
  });
});
