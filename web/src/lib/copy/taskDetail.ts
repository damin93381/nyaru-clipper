import { GLOSSARY_TERMS, SHARED_FALLBACK_COPY } from "./glossary";

export const TASK_DETAIL_COPY = {
  loading: {
    eyebrow: "正在加载任务",
    title: "正在获取任务详情...",
  },
  unavailable: {
    eyebrow: "任务不可用",
    title: "无法加载该任务。",
    unknownError: "未知错误",
  },
  summary: {
    eyebrow: "任务详情",
    title: (taskId: string) => `任务 ${taskId}`,
  },
  failure: {
    eyebrow: "可读失败摘要",
    title: (stageLabel: string) => `${stageLabel}阶段失败`,
    recovery: (stageLabel: string) => `可从 ${stageLabel} 重新尝试。上游已成功阶段保持不变，下游阶段继续等待。`,
    missingModel: {
      eyebrow: "ASR 模型恢复",
      title: "缺失模型处理",
      manualHint: "你也可以按下面目录手动放置模型文件，然后重新触发 ASR 阶段。",
      downloadIdle: "自动下载缺失模型",
      downloadPending: "正在下载缺失模型...",
    },
  },
  timeline: {
    eyebrow: "标准流水线",
    title: GLOSSARY_TERMS.stageTimeline,
    pollingActive: "每 3 秒轮询",
    pollingTerminal: "每 15 秒轮询",
    attempts: (count: number) => `尝试次数：${count}`,
    noStageLog: "暂无阶段日志",
  },
  artifacts: {
    eyebrow: GLOSSARY_TERMS.artifacts,
    title: "产物概览",
    count: (count: number) => `${count} 项`,
    empty: "阶段在任务目录中持久化产物后，会显示在这里。",
    noMetadata: SHARED_FALLBACK_COPY.noMetadata,
  },
} as const;
