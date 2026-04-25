export const CANONICAL_STAGES = [
  "ingest",
  "media_prep",
  "asr",
  "translation",
  "highlight",
  "export",
  "report",
] as const;

export const TERMINAL_STATUSES = ["success", "failed", "skipped"] as const;

export type TaskStageName = (typeof CANONICAL_STAGES)[number];
export type TaskStatus = "pending" | "running" | "success" | "failed" | "skipped";

export interface TaskStageRecord {
  name: TaskStageName;
  status: TaskStatus;
  summary: string | null;
  attempts: number;
}

export interface TaskDetail {
  task_id: string;
  source_url: string;
  normalized_source_url: string;
  source_video_id: string | null;
  status: TaskStatus;
  stages: TaskStageRecord[];
  created?: boolean;
}

export interface CreateTaskPayload {
  source_url: string;
}

export interface ArtifactRecord {
  id: number;
  task_id: string;
  stage_name: string;
  kind: string;
  path: string;
  metadata_json: string;
}

export interface StageLogSummary {
  stage_name: string;
  status: TaskStatus;
  summary: string | null;
  log_path: string;
}

export interface SubtitleArtifactSegment {
  id: string;
  start_seconds: number;
  end_seconds: number;
  text: string;
  translated_text?: string;
}

export interface SubtitleArtifactPayload {
  segments: SubtitleArtifactSegment[];
}

export interface HighlightWorkspaceCandidate {
  candidate_id?: number;
  rank: number;
  start_s: number;
  end_s: number;
  score: number;
  reasons: string[];
  default_range?: {
    start_s: number;
    end_s: number;
  };
}

export interface HighlightArtifactPayload {
  candidate_count?: number;
  no_candidates?: string | null;
  candidates: HighlightWorkspaceCandidate[];
}

export interface ClipExportPayload {
  candidate_id: number;
  start_s?: number;
  end_s?: number;
}

export interface ClipExportResponse {
  task_id: string;
  candidate_id: number;
  start_s: number;
  end_s: number;
  path: string;
  filename: string;
  artifact_id: number;
}

export function isTerminalStatus(status: TaskStatus | null | undefined): boolean {
  return Boolean(status && TERMINAL_STATUSES.includes(status as (typeof TERMINAL_STATUSES)[number]));
}

export function formatStageLabel(stageName: string): string {
  return stageName.replace(/_/g, " ");
}

export function humanizeSummary(summary: string | null | undefined): string {
  if (!summary) {
    return "Waiting for this stage to start.";
  }

  const normalized = summary.replace(/[_-]+/g, " ").trim();
  if (!normalized) {
    return "Waiting for this stage to start.";
  }

  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function safeParseMetadata(metadataJson: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(metadataJson) as Record<string, unknown>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}
