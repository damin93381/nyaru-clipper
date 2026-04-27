export const GLOSSARY_TERMS = {
  task: "任务",
  newTask: "新建任务",
  workspace: "工作区",
  stage: "阶段",
  stageTimeline: "阶段时间线",
  artifact: "产物",
  artifacts: "产物",
  environmentStatus: "环境状态",
  highlightCandidates: "高光候选",
  downloads: "下载",
  exportedClips: "已导出片段",
} as const;

export const TASK_STATUS_LABELS = {
  pending: "待处理",
  running: "运行中",
  success: "成功",
  failed: "失败",
  skipped: "已跳过",
} as const;

export const STAGE_LABELS = {
  ingest: "采集",
  media_prep: "媒体准备",
  asr: "语音转写",
  translation: "翻译",
  highlight: "高光",
  export: "导出",
  report: "报告",
} as const;

export const KNOWN_REASON_CODE_LABELS = {
  laughter_phrase: "笑声片段",
  emphasis_punctuation: "强调标点",
} as const;

export const KNOWN_SUMMARY_LABELS = {
  translation_failed: "翻译失败",
} as const;

export const ENVIRONMENT_STATUS_LABELS = {
  ok: "正常",
  warning: "警告",
  error: "错误",
} as const;

export const ENVIRONMENT_AVAILABILITY_LABELS = {
  satisfied: "已满足",
  needsAttention: "需要关注",
  unavailable: "不可用",
} as const;

export const SHARED_FALLBACK_COPY = {
  waitingForStage: "等待该阶段开始。",
  noReasonCode: "暂无原因代码。",
  noMetadata: "该产物暂无元数据。",
} as const;

export function getTaskStatusLabel(status: string): string {
  return TASK_STATUS_LABELS[status as keyof typeof TASK_STATUS_LABELS] ?? status;
}

export function getStageLabel(stageName: string): string {
  return STAGE_LABELS[stageName as keyof typeof STAGE_LABELS] ?? stageName;
}

export function getReasonCodeLabel(reasonCode: string | null | undefined): string {
  const normalized = reasonCode?.trim();

  if (!normalized) {
    return SHARED_FALLBACK_COPY.noReasonCode;
  }

  return KNOWN_REASON_CODE_LABELS[normalized as keyof typeof KNOWN_REASON_CODE_LABELS] ?? reasonCode;
}

export function getSummaryLabel(summary: string | null | undefined): string {
  const normalized = summary?.trim();

  if (!normalized) {
    return SHARED_FALLBACK_COPY.waitingForStage;
  }

  return KNOWN_SUMMARY_LABELS[normalized as keyof typeof KNOWN_SUMMARY_LABELS] ?? summary;
}

export function getEnvironmentStatusLabel(status: string): string {
  return ENVIRONMENT_STATUS_LABELS[status as keyof typeof ENVIRONMENT_STATUS_LABELS] ?? status;
}

export function getEnvironmentAvailabilityLabel(key: string): string {
  return ENVIRONMENT_AVAILABILITY_LABELS[key as keyof typeof ENVIRONMENT_AVAILABILITY_LABELS] ?? key;
}
