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
    device_name: "AMD Radeon RX 7800 XT",
    hip_version: "6.1.2",
    kind: "cuda",
    torch_available: true,
    torch_build_family: "rocm",
    torch_version: "2.6.0+rocm6.1",
  },
  dependencies: {
    tools: {},
    python: {},
  },
  issues: [],
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
    device_name: null,
    hip_version: null,
    kind: "cpu",
    torch_available: true,
    torch_build_family: "cpu",
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
  issues: [],
  warnings: ["GPU runtime was not detected; backend is operating in cpu-only mode."],
};

const wslCudaMismatchCapabilities: RuntimeCapabilities = {
  status: "error",
  detected_profile: "cpu-only",
  platform: {
    is_wsl: true,
    machine: "x86_64",
    release: "6.8.0-microsoft-standard-WSL2",
    system: "linux",
    version: "#1 SMP PREEMPT_DYNAMIC",
  },
  accelerator: {
    available: false,
    backend: "cpu",
    cuda_version: "12.8",
    device_count: 0,
    device_name: null,
    hip_version: null,
    kind: "cpu",
    torch_available: true,
    torch_build_family: "cuda",
    torch_version: "2.8.0+cu128",
  },
  dependencies: {
    tools: {},
    python: {},
  },
  issues: [
    {
      code: "wrong_torch_build_cuda_on_wsl",
      message: "WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm build.",
      severity: "error",
    },
  ],
  warnings: [
    "WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.",
    "GPU runtime was not detected; backend is operating in cpu-only mode.",
  ],
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

  it("renders a targeted WSL ROCm remediation message for CUDA torch wheels on WSL", () => {
    render(<EnvironmentStatusCard capabilities={wslCudaMismatchCapabilities} />);

    expect(screen.getByTestId("environment-status-card")).toHaveClass("environment-status-card--danger");
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(
      screen.getByText("This WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm runtime."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Use the dedicated WSL ROCm backend environment so startup stays non-blocking while operators still see the exact wheel mismatch.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("No accelerator detected · torch cuda build")).toBeInTheDocument();
    expect(
      screen.getByText("WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm build."),
    ).toBeInTheDocument();
  });
});
