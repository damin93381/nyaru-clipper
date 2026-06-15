import {
	getStageLabel,
	getSummaryLabel,
	getTaskStatusLabel,
} from "./copy/glossary";

export const CANONICAL_STAGES = [
	"ingest",
	"media_prep",
	"asr",
	"translation",
	"highlight",
	"export",
	"report",
] as const;

export const TERMINAL_STATUSES = ["success", "failed", "cancelled", "skipped"] as const;

export type TaskStageName = (typeof CANONICAL_STAGES)[number];
export type TaskStatus =
	| "pending"
	| "running"
	| "cancel_requested"
	| "success"
	| "failed"
	| "cancelled"
	| "skipped";

export type TaskFailureCode =
	| "unknown_failure"
	| "asr_missing_model"
	| "asr_oom"
	| "asr_alignment_failed"
	| "asr_child_failed"
	| "malformed_progress_event"
	| "stale_job_recovered"
	| "cancelled";

export type RecoveryActionId =
	| "retry_stage"
	| "download_asr_model"
	| "view_logs"
	| string;

export interface TaskRecoveryAction {
	id: RecoveryActionId;
	enabled: boolean;
	method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | string;
	label?: string;
	label_key?: string;
	description_key?: string;
	disabled_reason?: string | null;
	endpoint?: string;
	href?: string;
	payload?: Record<string, unknown> | null;
	confirmation_required?: boolean;
	success_behavior?: string;
}

export type ArtifactReadinessStatus =
	| "ready"
	| "not_ready"
	| "missing"
	| "failed";

export interface ArtifactReadinessRecord {
	kind: string;
	stage_name: TaskStageName | string;
	status: ArtifactReadinessStatus;
	readiness?: ArtifactReadinessStatus;
	artifact_id?: number | null;
	path?: string | null;
}

export interface TaskExecutionControlState {
	cancel_requested?: boolean;
	force_kill_requested?: boolean;
	active_process_group_id?: number | null;
}

export const ASR_EXECUTION_PHASES = [
	"model_load",
	"vad",
	"transcribe",
	"align",
	"persist",
] as const;

export type AsrExecutionPhaseName = (typeof ASR_EXECUTION_PHASES)[number];
export type ExecutionProgressStageName = "asr";
export type ExecutionProgressPhaseStatus =
	| "pending"
	| "running"
	| "success"
	| "failed";

export interface ExecutionProgressPhase {
	name: AsrExecutionPhaseName;
	status: ExecutionProgressPhaseStatus;
	elapsed_ms: number | null;
}

export interface TaskExecutionProgress {
	stage_name: ExecutionProgressStageName;
	current_phase: AsrExecutionPhaseName;
	phase_index: number;
	phase_count: number;
	phase_started_at: string | null;
	heartbeat_at: string | null;
	latest_message: string | null;
	phases: ExecutionProgressPhase[];
}

export interface TaskStageRecord {
	name: TaskStageName;
	status: TaskStatus;
	summary: string | null;
	failure_code?: TaskFailureCode | null;
	recovery_actions?: TaskRecoveryAction[];
	attempts: number;
}

export interface TaskDetail {
	task_id: string;
	source_url: string;
	normalized_source_url: string;
	source_video_id: string | null;
	status: TaskStatus;
	failure_code?: TaskFailureCode | null;
	recovery_actions?: TaskRecoveryAction[];
	artifact_readiness?: ArtifactReadinessRecord[];
	log_records?: StageLogSummary[];
	execution_control?: TaskExecutionControlState;
	stages: TaskStageRecord[];
	execution_progress?: TaskExecutionProgress;
	failure_recovery?: AsrMissingModelRecovery;
	created?: boolean;
}

export interface CreateTaskPayload {
	source_url: string;
}

export type AsrMissingModelKey = "whisperx" | "alignment";
export type AsrMissingModelStatus = "missing" | "ready" | "downloaded";

export interface AsrMissingModelDescriptor {
	key: AsrMissingModelKey;
	label: string;
	status: AsrMissingModelStatus;
	target_dir: string;
	repo_id: string;
	download_supported: boolean;
}

export interface AsrMissingModelRecovery {
	stage: "asr";
	kind: "missing_model";
	message: string;
	models: AsrMissingModelDescriptor[];
}

export interface DownloadAsrModelsPayload {
	model_keys: AsrMissingModelKey[];
}

export interface DownloadAsrModelsResponse {
	stage: "asr";
	kind: "missing_model";
	models: AsrMissingModelDescriptor[];
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
	display_label?: string;
	safe_summary?: string | null;
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

export type RuntimeCapabilityStatus = "ok" | "warning" | "error";

export interface RuntimeCapabilityPlatform {
	is_wsl: boolean;
	machine: string;
	release: string;
	system: string;
	version: string;
}

export interface RuntimeCapabilityAccelerator {
	available: boolean;
	backend: string;
	cuda_version: string | null;
	device_count: number;
	device_name: string | null;
	hip_version: string | null;
	kind: string;
	torch_available: boolean;
	torch_build_family: string | null;
	torch_version: string | null;
}

export interface RuntimeCapabilityIssue {
	code: string;
	message: string;
	severity: string;
}

export interface RuntimeDependencyCheck {
	available: boolean;
	status: string;
	binary?: string;
	module?: string;
	path?: string | null;
	version?: string | null;
}

export interface RuntimeCapabilities {
	status: RuntimeCapabilityStatus;
	detected_profile: string;
	platform: RuntimeCapabilityPlatform;
	accelerator: RuntimeCapabilityAccelerator;
	dependencies: {
		tools: Record<string, RuntimeDependencyCheck>;
		python: Record<string, RuntimeDependencyCheck>;
	};
	issues: RuntimeCapabilityIssue[];
	warnings: string[];
}

export const FULL_FUNCTION_RUNTIME_PROFILES = [
	"linux-cuda",
	"wsl-rocm",
] as const;

export function satisfiesFullFunctionProfile(
	capabilities: Pick<RuntimeCapabilities, "status" | "detected_profile">,
): boolean {
	return (
		capabilities.status === "ok" &&
		FULL_FUNCTION_RUNTIME_PROFILES.includes(
			capabilities.detected_profile as (typeof FULL_FUNCTION_RUNTIME_PROFILES)[number],
		)
	);
}

export function isTerminalStatus(
	status: TaskStatus | null | undefined,
): boolean {
	return Boolean(
		status &&
			TERMINAL_STATUSES.includes(status as (typeof TERMINAL_STATUSES)[number]),
	);
}

export function formatStageLabel(stageName: string): string {
	const mappedLabel = getStageLabel(stageName);

	if (mappedLabel !== stageName) {
		return mappedLabel;
	}

	return stageName.replace(/_/g, " ");
}

export function formatTaskStatusLabel(status: string): string {
	return getTaskStatusLabel(status);
}

export function humanizeSummary(summary: string | null | undefined): string {
	const mappedLabel = getSummaryLabel(summary);

	if (mappedLabel !== summary) {
		return mappedLabel;
	}

	return summary ?? mappedLabel;
}

export function safeParseMetadata(
	metadataJson: string,
): Record<string, unknown> {
	try {
		const parsed = JSON.parse(metadataJson) as Record<string, unknown>;
		return parsed && typeof parsed === "object" ? parsed : {};
	} catch {
		return {};
	}
}
