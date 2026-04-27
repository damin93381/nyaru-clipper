import type { RuntimeCapabilities, RuntimeCapabilityStatus } from "../types";

import {
  ENVIRONMENT_AVAILABILITY_LABELS,
  ENVIRONMENT_STATUS_LABELS,
  GLOSSARY_TERMS,
} from "./glossary";

type CardTone = "healthy" | "warning" | "danger";

function hasIssue(capabilities: RuntimeCapabilities, code: string): boolean {
  return capabilities.issues.some((issue) => issue.code === code);
}

export function getEnvironmentStatusBadgeLabel(status: RuntimeCapabilityStatus): string {
  return ENVIRONMENT_STATUS_LABELS[status];
}

export function getEnvironmentCardTone(status: RuntimeCapabilityStatus): CardTone {
  switch (status) {
    case "ok":
      return "healthy";
    case "warning":
      return "warning";
    case "error":
      return "danger";
  }
}

export function describeEnvironmentAcceleration(capabilities: RuntimeCapabilities): string {
  const { accelerator } = capabilities;

  if (!accelerator.available) {
    if (accelerator.torch_build_family && accelerator.torch_build_family !== "unknown") {
      return `未检测到可用加速设备 · torch ${accelerator.torch_build_family} 构建`;
    }

    return "未检测到可用加速设备";
  }

  const deviceLabel = accelerator.device_count === 1 ? "个设备" : "个设备";
  const deviceName = accelerator.device_name ? ` · ${accelerator.device_name}` : "";
  const buildFamily = accelerator.torch_build_family ? ` · torch ${accelerator.torch_build_family}` : "";

  return `${accelerator.backend} · ${accelerator.device_count} ${deviceLabel}${deviceName}${buildFamily}`;
}

export function getEnvironmentPrimaryMessage(capabilities: RuntimeCapabilities, fullFunctionSatisfied: boolean): string {
  if (fullFunctionSatisfied) {
    return "运行时检查表明当前工作站已满足预期的完整功能配置。";
  }

  if (hasIssue(capabilities, "wrong_torch_build_cuda_on_wsl")) {
    return "当前 WSL 主机正在使用 CUDA 构建的 torch wheel，而不是专用的 ROCm 运行环境。";
  }

  return "当前环境尚未满足预期的完整功能配置。";
}

export function getEnvironmentSupportMessage(capabilities: RuntimeCapabilities, fullFunctionSatisfied: boolean): string {
  if (fullFunctionSatisfied) {
    return "当前运行配置可使用 GPU 加速处理。";
  }

  if (hasIssue(capabilities, "wrong_torch_build_cuda_on_wsl")) {
    return "请切换到专用的 WSL ROCm 后端环境，以保持启动流程非阻塞，并让操作人员看到准确的 wheel 不匹配信息。";
  }

  return "这些警告不会阻止任务提交或任务审阅，但可能降低处理能力。";
}

export const ENVIRONMENT_STATUS_COPY = {
  card: {
    eyebrow: GLOSSARY_TERMS.environmentStatus,
    title: GLOSSARY_TERMS.environmentStatus,
  },
  loading: {
    description: "正在检查当前工作站配置的后端运行能力。",
  },
  unavailable: {
    statusBadge: ENVIRONMENT_AVAILABILITY_LABELS.unavailable,
    attentionBadge: ENVIRONMENT_AVAILABILITY_LABELS.needsAttention,
    description: "运行能力检查暂时不可用。任务界面仍可继续使用，系统稍后会再次重试。",
  },
  satisfiedBadge: ENVIRONMENT_AVAILABILITY_LABELS.satisfied,
  attentionBadge: ENVIRONMENT_AVAILABILITY_LABELS.needsAttention,
  metadata: {
    activeProfile: "当前配置",
    acceleration: "加速能力",
  },
  sections: {
    warnings: "当前警告",
    issues: "已检测问题",
  },
} as const;
