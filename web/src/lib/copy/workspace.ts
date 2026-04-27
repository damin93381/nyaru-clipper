import { GLOSSARY_TERMS, getReasonCodeLabel } from "./glossary";

export const WORKSPACE_DOWNLOAD_LABELS = {
  subtitle_srt: "下载中文字幕",
  bilingual_subtitle_srt: "下载双语字幕",
  transcript_json: "下载中文字幕 JSON",
  bilingual_transcript_json: "下载双语字幕 JSON",
  task_report_markdown: "下载任务报告",
  clip_export: "下载已导出片段",
} as const;

export function getWorkspaceDownloadLabel(kind: string): string {
  return WORKSPACE_DOWNLOAD_LABELS[kind as keyof typeof WORKSPACE_DOWNLOAD_LABELS] ?? `下载 ${kind}`;
}

export function formatWorkspaceReason(reasonCode: string | null | undefined): string {
  return getReasonCodeLabel(reasonCode);
}

export const WORKSPACE_COPY = {
  header: {
    eyebrow: GLOSSARY_TERMS.workspace,
    title: "字幕审阅与高光确认",
    badge: (taskId: string) => `任务 ${taskId} 工作区`,
  },
  subtitles: {
    eyebrow: "字幕",
    title: "中文字幕与双语字幕行",
    columns: {
      segment: "片段",
      chinese: "中文字幕",
      bilingual: "双语字幕",
    },
    missingBilingual: "暂无双语翻译。",
    empty: "转写产物可用后，字幕行会显示在这里。",
  },
	candidates: {
		eyebrow: GLOSSARY_TERMS.highlightCandidates,
		title: "排名候选确认",
    rank: (rank: number) => `排名 ${rank}`,
    score: (score: number) => `分数 ${score.toFixed(2)}`,
    reasonsLabel: "原因",
    defaultRangeLabel: "默认范围",
    startLabel: "开始（秒）",
    endLabel: "结束（秒）",
    confirmPending: "正在导出片段...",
    confirmIdle: "确认导出",
    zeroStateEyebrow: "零候选状态",
    zeroStateTitle: "暂无可用高光候选",
    zeroCandidateFallback: "当前没有高光候选通过当前分数阈值。",
		empty: "排名后的高光候选 JSON 产物可用后，会在这里显示详细信息。",
		exportFailed: "片段导出失败。",
		missingCandidateId: "候选片段缺少可导出的 candidate_id。",
	},
  downloads: {
    eyebrow: GLOSSARY_TERMS.downloads,
    title: "产物下载",
    empty: "字幕、报告和片段产物持久化后，会在这里显示下载操作。",
  },
  exportedClips: {
    eyebrow: GLOSSARY_TERMS.exportedClips,
    title: "可下载的 MP4 产物",
    badge: "片段导出",
    candidate: (candidateId: number) => `候选 ${candidateId}`,
    downloadLabel: "下载已导出片段",
    empty: "已确认导出的片段会以可下载的 MP4 产物显示在这里。",
  },
} as const;
