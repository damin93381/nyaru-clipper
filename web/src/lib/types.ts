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

export const TERMINAL_STATUSES = ["success", "failed", "skipped"] as const;

export type TaskStageName = (typeof CANONICAL_STAGES)[number];
export type TaskStatus =
	| "pending"
	| "running"
	| "success"
	| "failed"
	| "skipped";

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
