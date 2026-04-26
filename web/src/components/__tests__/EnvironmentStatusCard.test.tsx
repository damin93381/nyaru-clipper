import { render, screen } from "@testing-library/react";

import type { RuntimeCapabilities } from "../../lib/types";
import { EnvironmentStatusCard } from "../EnvironmentStatusCard";

const healthyCapabilities: RuntimeCapabilities = {
  status: "ok",
  detected_profile: "wsl-rocm",
  platform: {
    is_wsl: true,
    machine: "x86_64",
    release: "6.8.0-microsoft-standard-WSL2",
    system: "linux",
    version: "#1 SMP PREEMPT_DYNAMIC",
  },
  accelerator: {
    available: true,
    backend: "rocm",
    cuda_version: null,
    device_count: 1,
    hip_version: "6.1.2",
    kind: "cuda",
    torch_available: true,
    torch_version: "2.6.0+rocm6.1",
  },
  dependencies: {
    tools: {},
    python: {},
  },
  warnings: [],
};

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
    tools: {
      ffmpeg: {
        available: true,
        binary: "ffmpeg",
        path: "/usr/bin/ffmpeg",
        status: "ok",
      },
    },
    python: {},
  },
  warnings: ["GPU runtime was not detected; backend is operating in cpu-only mode."],
};

describe("EnvironmentStatusCard", () => {
  it("renders a healthy runtime snapshot with a satisfied full-function profile signal", () => {
    render(<EnvironmentStatusCard capabilities={healthyCapabilities} />);

    expect(screen.getByRole("heading", { name: /environment status/i })).toBeInTheDocument();
    expect(screen.getByTestId("environment-status-card")).toHaveClass("environment-status-card--healthy");
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("wsl-rocm")).toBeInTheDocument();
    expect(screen.getByText("Satisfied")).toBeInTheDocument();
    expect(screen.getByText(/runtime checks report the expected full-function profile/i)).toBeInTheDocument();
    expect(screen.queryByText(/active warnings/i)).not.toBeInTheDocument();
  });

  it("renders warning-only capability gaps without hiding the warning details", () => {
    render(<EnvironmentStatusCard capabilities={warningCapabilities} />);

    expect(screen.getByTestId("environment-status-card")).toHaveClass("environment-status-card--warning");
    expect(screen.getByText("Warning")).toBeInTheDocument();
    expect(screen.getByText("cpu-only")).toBeInTheDocument();
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText(/warnings do not block task submission or task review/i)).toBeInTheDocument();
    expect(screen.getByText(/gpu runtime was not detected/i)).toBeInTheDocument();
  });
});
