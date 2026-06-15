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
  progress: {
    eyebrow: "ASR 运行态",
    title: "ASR 执行进度",
    currentPhaseLabel: "当前阶段",
    heartbeatLabel: "最近心跳",
    phaseStartedAtLabel: "阶段开始",
    latestMessageLabel: "最近消息",
    latestMessageFallback: "暂无阶段消息",
    heartbeatFallback: "等待首次心跳",
    phaseStartedAtFallback: "等待该阶段开始",
    cancelRequestedTitle: "取消请求中",
    cancelRequestedSummary: "已请求取消，正在等待当前 ASR 执行停止。",
    phaseElapsed: (elapsed: string) => elapsed,
    phaseActive: "进行中",
    phasePending: "等待开始",
    phaseLabels: {
      model_load: "模型加载",
      vad: "语音活动检测",
      transcribe: "语音转写",
      align: "字幕对齐",
      persist: "结果落盘",
    },
  },
  failure: {
    eyebrow: "可读失败摘要",
    title: (stageLabel: string) => `${stageLabel}阶段失败`,
    recovery: (stageLabel: string) => `可从 ${stageLabel} 重新尝试。上游已成功阶段保持不变，下游阶段继续等待。`,
    fallbackMessages: {
      unknown_failure: "处理失败，请查看安全日志摘要后重试该阶段。",
      asr_oom: "ASR 运行时显存不足，请释放 GPU 资源后重试。",
      asr_alignment_failed: "ASR 字幕对齐失败，请查看日志并重试 ASR。",
      asr_child_failed: "ASR 子进程失败，请查看安全日志摘要。",
      malformed_progress_event: "ASR 进度事件异常，当前执行已被标记为失败。",
      stale_job_recovered: "检测到上次运行遗留的中断任务，请重试失败阶段。",
      cancelled: "任务已取消。",
    },
    disabledReasons: {
      model_not_ready: "缺失模型下载完成后才能重试。",
      task_not_failed: "只有失败任务可以重试阶段。",
      stage_not_retryable: "当前阶段暂不可重试。",
      cancelled: "已取消任务不提供重试操作。",
      unknown: "该恢复操作当前不可用。",
    },
    actions: {
      retry_stage: {
        label: "重试此阶段",
        description: "从失败阶段重新进入队列，上游成功阶段保持不变。",
      },
      download_asr_model: {
        label: "下载缺失模型",
        description: "下载 ASR 所需模型文件，完成后可重试 ASR 阶段。",
      },
      view_logs: {
        label: "查看日志",
        description: "查看安全日志摘要和技术日志路径。",
      },
    },
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
