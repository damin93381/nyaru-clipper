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

    expect(screen.getByRole("heading", { name: "环境状态" })).toBeInTheDocument();
    expect(screen.getByTestId("environment-status-card")).toHaveClass("environment-status-card--healthy");
    expect(screen.getByText("正常")).toBeInTheDocument();
    expect(screen.getByText("wsl-rocm")).toBeInTheDocument();
    expect(screen.getByText("已满足")).toBeInTheDocument();
    expect(screen.getByText("运行时检查表明当前工作站已满足预期的完整功能配置。")).toBeInTheDocument();
    expect(screen.getByText("当前运行配置可使用 GPU 加速处理。")).toBeInTheDocument();
    expect(screen.getByText("当前配置")).toBeInTheDocument();
    expect(screen.getByText("加速能力")).toBeInTheDocument();
    expect(screen.queryByText("当前警告")).not.toBeInTheDocument();
  });

  it("renders warning-only capability gaps without hiding the warning details", () => {
    render(<EnvironmentStatusCard capabilities={warningCapabilities} />);

    expect(screen.getByTestId("environment-status-card")).toHaveClass("environment-status-card--warning");
    expect(screen.getByText("警告")).toBeInTheDocument();
    expect(screen.getByText("cpu-only")).toBeInTheDocument();
    expect(screen.getByText("需要关注")).toBeInTheDocument();
    expect(screen.getByText("当前环境尚未满足预期的完整功能配置。")).toBeInTheDocument();
    expect(screen.getByText("这些警告不会阻止任务提交或任务审阅，但可能降低处理能力。")).toBeInTheDocument();
    expect(screen.getByText("当前警告")).toBeInTheDocument();
    expect(screen.getByText(/gpu runtime was not detected/i)).toBeInTheDocument();
  });

  it("renders a targeted WSL ROCm remediation message for CUDA torch wheels on WSL", () => {
    render(<EnvironmentStatusCard capabilities={wslCudaMismatchCapabilities} />);

    expect(screen.getByTestId("environment-status-card")).toHaveClass("environment-status-card--danger");
    expect(screen.getByText("错误")).toBeInTheDocument();
    expect(
      screen.getByText("当前 WSL 主机正在使用 CUDA 构建的 torch wheel，而不是专用的 ROCm 运行环境。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "请切换到专用的 WSL ROCm 后端环境，以保持启动流程非阻塞，并让操作人员看到准确的 wheel 不匹配信息。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("未检测到可用加速设备 · torch cuda 构建")).toBeInTheDocument();
    expect(screen.getByText("已检测问题")).toBeInTheDocument();
    expect(
      screen.getByText("WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm build."),
    ).toBeInTheDocument();
  });
});
