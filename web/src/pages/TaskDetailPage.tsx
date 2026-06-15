import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";

import {
	ApiError,
	downloadAsrModels,
	getTaskArtifacts,
	getTaskDetail,
	getTaskLogs,
	getTaskStages,
	retryTaskFromStage,
} from "../lib/api";
import { GLOSSARY_TERMS } from "../lib/copy/glossary";
import { TASK_DETAIL_COPY } from "../lib/copy/taskDetail";
import {
	classifyTaskState,
	getPrimaryAction,
	isRetryable,
	type TaskState,
} from "../lib/taskState";
import {
	type ArtifactRecord,
	type AsrExecutionPhaseName,
	type AsrMissingModelRecovery,
	CANONICAL_STAGES,
	type ExecutionProgressPhase,
	formatStageLabel,
	formatTaskStatusLabel,
	humanizeSummary,
	isTerminalStatus,
	type StageLogSummary,
	safeParseMetadata,
	type TaskDetail,
	type TaskExecutionProgress,
	type TaskFailureCode,
	type TaskStageName,
	type TaskStageRecord,
	type TaskStatus,
} from "../lib/types";
import { WorkspacePage } from "./WorkspacePage";

interface StageRow {
	name: string;
	status: TaskStatus;
	attempts: number;
	summary: string;
	displayLabel: string | null;
	logPath: string | null;
}

export function getPollingInterval(
	status: TaskStatus | null | undefined,
): number {
	return isTerminalStatus(status) ? 15_000 : 3_000;
}

function getStatusTone(status: TaskStatus): string {
	if (status === "cancel_requested") {
		return "status-badge status-badge--warning";
	}

	return `status-badge status-badge--${status}`;
}

function formatUtcTimestamp(timestamp: string | null | undefined): string {
	if (!timestamp) {
		return TASK_DETAIL_COPY.progress.heartbeatFallback;
	}

	const value = new Date(timestamp);
	if (Number.isNaN(value.getTime())) {
		return timestamp;
	}

	const year = value.getUTCFullYear();
	const month = String(value.getUTCMonth() + 1).padStart(2, "0");
	const day = String(value.getUTCDate()).padStart(2, "0");
	const hours = String(value.getUTCHours()).padStart(2, "0");
	const minutes = String(value.getUTCMinutes()).padStart(2, "0");
	const seconds = String(value.getUTCSeconds()).padStart(2, "0");

	return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} UTC`;
}

function formatElapsedMs(elapsedMs: number | null | undefined): string | null {
	if (
		elapsedMs === null ||
		elapsedMs === undefined ||
		Number.isNaN(elapsedMs)
	) {
		return null;
	}

	return `${(elapsedMs / 1000).toFixed(1)}s`;
}

function formatAsrPhaseLabel(phase: AsrExecutionPhaseName): string {
	return TASK_DETAIL_COPY.progress.phaseLabels[phase] ?? phase;
}

function getProgressPhaseTone(
	status: ExecutionProgressPhase["status"],
): string {
	if (status === "failed") {
		return "status-badge status-badge--failed";
	}

	if (status === "success") {
		return "status-badge status-badge--success";
	}

	if (status === "running") {
		return "status-badge status-badge--running";
	}

	return "status-badge status-badge--pending";
}

function buildAsrStageSummary(
	taskStatus: TaskStatus,
	executionProgress: TaskExecutionProgress | undefined,
): string | null {
	if (taskStatus === "cancel_requested") {
		return TASK_DETAIL_COPY.progress.cancelRequestedSummary;
	}

	if (executionProgress?.latest_message) {
		return executionProgress.latest_message;
	}

	if (executionProgress) {
		return `${formatAsrPhaseLabel(executionProgress.current_phase)}进行中`;
	}

	return null;
}

function isAsrStageActive(
	stages: TaskStageRecord[],
	taskStatus: TaskStatus | null | undefined,
): boolean {
	const asrStage = stages.find((stage) => stage.name === "asr");

	return Boolean(
		asrStage &&
			asrStage.status === "running" &&
			(taskStatus === "running" || taskStatus === "cancel_requested"),
	);
}

function buildStageRows(
	stages: TaskStageRecord[],
	logs: StageLogSummary[],
	options: {
		taskStatus: TaskStatus;
		executionProgress?: TaskExecutionProgress;
	},
): StageRow[] {
	const stagesByName = new Map(stages.map((stage) => [stage.name, stage]));
	const logsByStage = new Map(logs.map((log) => [log.stage_name, log]));

	return CANONICAL_STAGES.map((stageName) => {
		const stage = stagesByName.get(stageName);
		const log = logsByStage.get(stageName);
		const progressSummary =
			stageName === "asr" && stage?.status === "running"
				? buildAsrStageSummary(options.taskStatus, options.executionProgress)
				: null;
		const rawSummary =
			progressSummary ??
			log?.safe_summary ??
			log?.summary ??
			stage?.summary ??
			null;
		const status =
			stageName === "asr" &&
			stage?.status === "running" &&
			options.taskStatus === "cancel_requested"
				? "cancel_requested"
				: (stage?.status ?? log?.status ?? "pending");

		return {
			name: stageName,
			status,
			attempts: stage?.attempts ?? 0,
			summary: humanizeSummary(rawSummary),
			displayLabel: log?.display_label ?? null,
			logPath: log?.log_path ?? null,
		};
	});
}

function findFailedStage(task: TaskDetail): TaskStageRecord | null {
	return task.stages.find((stage) => stage.status === "failed") ?? null;
}

function getTaskFailureCode(
	task: TaskDetail,
	failedStage: TaskStageRecord | null,
): TaskFailureCode | null {
	return task.failure_code ?? failedStage?.failure_code ?? null;
}

function getFailureSummary(
	task: TaskDetail,
	failedStage: TaskStageRecord | null,
): string {
	const failureCode = getTaskFailureCode(task, failedStage);
	if (failureCode && TASK_DETAIL_COPY.failure.fallbackMessages[failureCode]) {
		return TASK_DETAIL_COPY.failure.fallbackMessages[failureCode];
	}

	return humanizeSummary(failedStage?.summary ?? task.failure_code ?? null);
}

function getPanelTone(state: TaskState): string {
	if (
		state === "failed_retryable" ||
		state === "failed_asr_missing_model" ||
		state === "failed_terminal" ||
		state === "artifact_failed" ||
		state === "worker_stale_recovery"
	) {
		return "panel panel--danger task-state-panel";
	}

	if (state === "cancelled") {
		return "panel panel--muted task-state-panel";
	}

	return "panel task-state-panel";
}

function getActionCopy(
	actionId: "retry_stage" | "download_asr_model" | "view_logs",
) {
	return TASK_DETAIL_COPY.failure.actions[actionId];
}

function formatArtifactName(path: string): string {
	const parts = path.split("/");
	return parts[parts.length - 1] || path;
}

function flattenMetadata(
	metadata: Record<string, unknown>,
	prefix = "",
): Array<[string, string]> {
	return Object.entries(metadata).flatMap(([key, value]) => {
		const label = prefix ? `${prefix}.${key}` : key;

		if (value === null || value === undefined) {
			return [];
		}

		if (Array.isArray(value)) {
			return [[label, value.join(", ")]];
		}

		if (typeof value === "object") {
			return flattenMetadata(value as Record<string, unknown>, label);
		}

		return [[label, String(value)]];
	});
}

function ArtifactCard({ artifact }: { artifact: ArtifactRecord }) {
	const metadataEntries = flattenMetadata(
		safeParseMetadata(artifact.metadata_json),
	);

	return (
		<article className="artifact-card">
			<div className="artifact-card__header">
				<strong>{artifact.kind}</strong>
				<span className="status-badge status-badge--success">
					{formatStageLabel(artifact.stage_name)}
				</span>
			</div>
			<p className="artifact-card__path">{formatArtifactName(artifact.path)}</p>
			{metadataEntries.length > 0 ? (
				<dl className="metadata-list">
					{metadataEntries.map(([label, value]) => (
						<div className="metadata-list__row" key={`${artifact.id}-${label}`}>
							<dt>{label}</dt>
							<dd>{value}</dd>
						</div>
					))}
				</dl>
			) : (
				<p className="support-copy">{TASK_DETAIL_COPY.artifacts.noMetadata}</p>
			)}
		</article>
	);
}

function AsrExecutionProgressPanel({
	executionProgress,
	taskStatus,
}: {
	executionProgress: TaskExecutionProgress;
	taskStatus: TaskStatus;
}) {
	const currentPhaseLabel = `${formatAsrPhaseLabel(executionProgress.current_phase)}（${executionProgress.phase_index} / ${executionProgress.phase_count}）`;
	const latestMessage =
		executionProgress.latest_message ??
		TASK_DETAIL_COPY.progress.latestMessageFallback;
	const phaseStartedAt = executionProgress.phase_started_at
		? formatUtcTimestamp(executionProgress.phase_started_at)
		: TASK_DETAIL_COPY.progress.phaseStartedAtFallback;

	return (
		<section className="panel">
			<div className="panel__header">
				<div>
					<p className="eyebrow">{TASK_DETAIL_COPY.progress.eyebrow}</p>
					<h3>{TASK_DETAIL_COPY.progress.title}</h3>
				</div>
				{taskStatus === "cancel_requested" ? (
					<span className="status-badge status-badge--warning">
						{TASK_DETAIL_COPY.progress.cancelRequestedTitle}
					</span>
				) : null}
			</div>

			<div className="summary-strip">
				<div>
					<span className="summary-strip__label">
						{TASK_DETAIL_COPY.progress.currentPhaseLabel}
					</span>
					<strong>{currentPhaseLabel}</strong>
				</div>
				{taskStatus === "cancel_requested" ? (
					<div>
						<span className="summary-strip__label">
							{TASK_DETAIL_COPY.progress.cancelRequestedTitle}
						</span>
						<strong>{TASK_DETAIL_COPY.progress.cancelRequestedSummary}</strong>
					</div>
				) : null}
			</div>

			<dl className="metadata-list">
				<div className="metadata-list__row">
					<dt>{TASK_DETAIL_COPY.progress.latestMessageLabel}</dt>
					<dd>{latestMessage}</dd>
				</div>
				<div className="metadata-list__row">
					<dt>{TASK_DETAIL_COPY.progress.heartbeatLabel}</dt>
					<dd>{formatUtcTimestamp(executionProgress.heartbeat_at)}</dd>
				</div>
				<div className="metadata-list__row">
					<dt>{TASK_DETAIL_COPY.progress.phaseStartedAtLabel}</dt>
					<dd>{phaseStartedAt}</dd>
				</div>
			</dl>

			<ol className="stage-list">
				{executionProgress.phases.map((phase) => {
					const elapsed = formatElapsedMs(phase.elapsed_ms);
					const helperText =
						elapsed ??
						(phase.status === "running"
							? TASK_DETAIL_COPY.progress.phaseActive
							: TASK_DETAIL_COPY.progress.phasePending);

					return (
						<li className="stage-card" key={phase.name}>
							<div className="stage-card__header">
								<div>
									<p className="stage-card__eyebrow">
										{TASK_DETAIL_COPY.progress.currentPhaseLabel}
									</p>
									<h4>{formatAsrPhaseLabel(phase.name)}</h4>
								</div>
								<span className={getProgressPhaseTone(phase.status)}>
									{formatTaskStatusLabel(phase.status)}
								</span>
							</div>
							<p>
								{elapsed
									? TASK_DETAIL_COPY.progress.phaseElapsed(elapsed)
									: helperText}
							</p>
						</li>
					);
				})}
			</ol>
		</section>
	);
}

function TaskStatePanel({
	task,
	state,
	failedStage,
	asrMissingModelRecovery,
	onRetry,
	onDownloadModels,
	retryPending,
	downloadPending,
	retryErrorMessage,
	downloadErrorMessage,
	downloadDisabled,
}: {
	task: TaskDetail;
	state: TaskState;
	failedStage: TaskStageRecord | null;
	asrMissingModelRecovery: AsrMissingModelRecovery | null;
	onRetry: (stageName: TaskStageName) => void;
	onDownloadModels: () => void;
	retryPending: boolean;
	downloadPending: boolean;
	retryErrorMessage: string | null;
	downloadErrorMessage: string | null;
	downloadDisabled: boolean;
}) {
	const primaryAction = getPrimaryAction(state);
	const failureSummary = getFailureSummary(task, failedStage);
	const failedStageLabel = failedStage
		? formatStageLabel(failedStage.name)
		: null;
	const canRetry = Boolean(
		failedStage &&
			isRetryable(task, failedStage.name) &&
			primaryAction === "retry_stage",
	);

	if (state === "queued" || state === "retry_in_progress") {
		return (
			<section className={getPanelTone(state)} aria-live="polite">
				<p className="eyebrow">{TASK_DETAIL_COPY.statePanels.queued.eyebrow}</p>
				<h3>{TASK_DETAIL_COPY.statePanels.queued.title}</h3>
				<p>{TASK_DETAIL_COPY.statePanels.queued.description}</p>
			</section>
		);
	}

	if (state === "active" || state === "force_kill_requested") {
		return (
			<section className={getPanelTone(state)} aria-live="polite">
				<div className="panel__header">
					<div>
						<p className="eyebrow">
							{TASK_DETAIL_COPY.statePanels.active.eyebrow}
						</p>
						<h3>{TASK_DETAIL_COPY.statePanels.active.title}</h3>
					</div>
					<span className={getStatusTone(task.status)}>
						{formatTaskStatusLabel(task.status)}
					</span>
				</div>
				<p>{TASK_DETAIL_COPY.statePanels.active.description}</p>
				<button className="secondary-button" disabled type="button">
					{TASK_DETAIL_COPY.statePanels.active.cancelAction}
				</button>
				<p className="support-copy">
					{TASK_DETAIL_COPY.statePanels.active.cancelUnavailable}
				</p>
			</section>
		);
	}

	if (state === "failed_asr_missing_model") {
		return (
			<section className={getPanelTone(state)} aria-live="polite">
				<p className="eyebrow">
					{TASK_DETAIL_COPY.statePanels.asrMissingModel.eyebrow}
				</p>
				<h3>{TASK_DETAIL_COPY.statePanels.asrMissingModel.title}</h3>
				<p>{asrMissingModelRecovery?.message ?? failureSummary}</p>
				{asrMissingModelRecovery ? (
					<>
						<p className="support-copy">
							{TASK_DETAIL_COPY.failure.missingModel.manualHint}
						</p>
						<dl className="metadata-list">
							{asrMissingModelRecovery.models.map((model) => (
								<div className="metadata-list__row" key={model.key}>
									<dt>{model.label}</dt>
									<dd>{model.target_dir}</dd>
								</div>
							))}
						</dl>
					</>
				) : null}
				<button
					className="primary-button"
					disabled={downloadDisabled || downloadPending}
					onClick={onDownloadModels}
					type="button"
				>
					{downloadPending
						? TASK_DETAIL_COPY.failure.missingModel.downloadPending
						: getActionCopy("download_asr_model").label}
				</button>
				{downloadErrorMessage ? (
					<p className="form-error">{downloadErrorMessage}</p>
				) : null}
			</section>
		);
	}

	if (
		state === "failed_retryable" ||
		state === "failed_terminal" ||
		state === "worker_stale_recovery" ||
		state === "artifact_failed" ||
		state === "artifact_missing"
	) {
		return (
			<section className={getPanelTone(state)} aria-live="polite">
				<p className="eyebrow">{TASK_DETAIL_COPY.statePanels.failed.eyebrow}</p>
				<h3>{TASK_DETAIL_COPY.statePanels.failed.title}</h3>
				<p>{failureSummary}</p>
				{failedStageLabel ? (
					<p>{TASK_DETAIL_COPY.failure.recovery(failedStageLabel)}</p>
				) : null}
				{canRetry && failedStage ? (
					<button
						className="primary-button"
						disabled={retryPending}
						onClick={() => onRetry(failedStage.name)}
						type="button"
					>
						{retryPending
							? TASK_DETAIL_COPY.statePanels.failed.retryPending
							: getActionCopy("retry_stage").label}
					</button>
				) : null}
				{retryErrorMessage ? (
					<p className="form-error">{retryErrorMessage}</p>
				) : null}
			</section>
		);
	}

	if (state === "cancelled") {
		return (
			<section className={getPanelTone(state)} aria-live="polite">
				<p className="eyebrow">
					{TASK_DETAIL_COPY.statePanels.cancelled.eyebrow}
				</p>
				<h3>{TASK_DETAIL_COPY.statePanels.cancelled.title}</h3>
				<p>{TASK_DETAIL_COPY.statePanels.cancelled.description}</p>
			</section>
		);
	}

	if (state === "success") {
		return (
			<section className={getPanelTone(state)} aria-live="polite">
				<p className="eyebrow">
					{TASK_DETAIL_COPY.statePanels.success.eyebrow}
				</p>
				<h3>{TASK_DETAIL_COPY.statePanels.success.title}</h3>
				<p>{TASK_DETAIL_COPY.statePanels.success.description}</p>
			</section>
		);
	}

	return null;
}

export function TaskDetailPage() {
	const params = useParams();
	const taskId = params.taskId ?? "";
	const queryClient = useQueryClient();

	const taskDetailQuery = useQuery({
		queryKey: ["task", taskId, "detail"],
		queryFn: () => getTaskDetail(taskId),
		enabled: Boolean(taskId),
		refetchInterval: (query) => getPollingInterval(query.state.data?.status),
	});

	const taskStatus = taskDetailQuery.data?.status;
	const executionProgress = taskDetailQuery.data?.execution_progress;
	const taskState = classifyTaskState(taskDetailQuery.data);

	const stageQuery = useQuery({
		queryKey: ["task", taskId, "stages"],
		queryFn: () => getTaskStages(taskId),
		enabled: Boolean(taskId),
		refetchInterval: () => getPollingInterval(taskStatus),
	});

	const artifactsQuery = useQuery({
		queryKey: ["task", taskId, "artifacts"],
		queryFn: () => getTaskArtifacts(taskId),
		enabled: Boolean(taskId),
		refetchInterval: () => getPollingInterval(taskStatus),
	});

	const logsQuery = useQuery({
		queryKey: ["task", taskId, "logs"],
		queryFn: () => getTaskLogs(taskId),
		enabled: Boolean(taskId),
		refetchInterval: () => getPollingInterval(taskStatus),
	});

	const stages = taskDetailQuery.data?.stages ?? stageQuery.data ?? [];
	const logs = taskDetailQuery.data?.log_records ?? logsQuery.data ?? [];
	const artifacts = artifactsQuery.data ?? [];

	const stageRows = useMemo(
		() =>
			buildStageRows(stages, logs, {
				taskStatus: taskStatus ?? "pending",
				executionProgress,
			}),
		[executionProgress, logs, stages, taskStatus],
	);
	const isActiveAsr = isAsrStageActive(stages, taskStatus);
	const failedStage = taskDetailQuery.data
		? findFailedStage(taskDetailQuery.data)
		: null;
	const failureRecovery = taskDetailQuery.data?.failure_recovery;
	const asrMissingModelRecovery: AsrMissingModelRecovery | null =
		failedStage?.name === "asr" &&
		failureRecovery?.stage === "asr" &&
		failureRecovery.kind === "missing_model"
			? failureRecovery
			: null;
	const downloadableModelKeys =
		asrMissingModelRecovery?.models
			.filter((model) => model.download_supported && model.status === "missing")
			.map((model) => model.key) ?? [];

	const retryStageMutation = useMutation({
		mutationFn: (stageName: TaskStageName) =>
			retryTaskFromStage(taskId, stageName),
		onSuccess: async () => {
			await Promise.all([
				queryClient.invalidateQueries({
					queryKey: ["task", taskId, "detail"],
				}),
				queryClient.invalidateQueries({
					queryKey: ["task", taskId, "stages"],
				}),
				queryClient.invalidateQueries({
					queryKey: ["task", taskId, "logs"],
				}),
			]);
		},
	});

	const downloadAsrModelsMutation = useMutation({
		mutationFn: () => downloadAsrModels(taskId, downloadableModelKeys),
		onSuccess: async () => {
			await Promise.all([
				queryClient.invalidateQueries({
					queryKey: ["task", taskId, "detail"],
				}),
				queryClient.invalidateQueries({
					queryKey: ["task", taskId, "stages"],
				}),
				queryClient.invalidateQueries({
					queryKey: ["task", taskId, "logs"],
				}),
			]);
		},
	});

	if (taskDetailQuery.isPending && !taskDetailQuery.data) {
		return (
			<section className="page">
				<div className="panel panel--loading">
					<p className="eyebrow">{TASK_DETAIL_COPY.loading.eyebrow}</p>
					<h2>{TASK_DETAIL_COPY.loading.title}</h2>
				</div>
			</section>
		);
	}

	if (
		taskDetailQuery.isError &&
		taskDetailQuery.error instanceof ApiError &&
		taskDetailQuery.error.status === 404
	) {
		return (
			<section className="page">
				<div className="panel panel--danger task-state-panel">
					<p className="eyebrow">{TASK_DETAIL_COPY.notFound.eyebrow}</p>
					<h2>{TASK_DETAIL_COPY.notFound.title}</h2>
					<p>{TASK_DETAIL_COPY.notFound.description}</p>
					<Link className="primary-button" to="/">
						{TASK_DETAIL_COPY.notFound.action}
					</Link>
				</div>
			</section>
		);
	}

	if (taskDetailQuery.isError || !taskDetailQuery.data) {
		return (
			<section className="page">
				<div className="panel panel--danger">
					<p className="eyebrow">{TASK_DETAIL_COPY.unavailable.eyebrow}</p>
					<h2>{TASK_DETAIL_COPY.unavailable.title}</h2>
					<p>
						{taskDetailQuery.error instanceof Error
							? taskDetailQuery.error.message
							: TASK_DETAIL_COPY.unavailable.unknownError}
					</p>
				</div>
			</section>
		);
	}

	return (
		<section className="page detail-page">
			<div className="panel task-summary">
				<div>
					<p className="eyebrow">{TASK_DETAIL_COPY.summary.eyebrow}</p>
					<h2>
						{TASK_DETAIL_COPY.summary.title(taskDetailQuery.data.task_id)}
					</h2>
					<p className="support-copy">
						{taskDetailQuery.data.normalized_source_url}
					</p>
				</div>
				<div className="task-summary__badges">
					<span className={getStatusTone(taskDetailQuery.data.status)}>
						{formatTaskStatusLabel(taskDetailQuery.data.status)}
					</span>
					{taskDetailQuery.data.source_video_id ? (
						<span className="pill">{taskDetailQuery.data.source_video_id}</span>
					) : null}
				</div>
			</div>

			<TaskStatePanel
				asrMissingModelRecovery={asrMissingModelRecovery}
				downloadDisabled={downloadableModelKeys.length === 0}
				downloadErrorMessage={
					downloadAsrModelsMutation.isError
						? downloadAsrModelsMutation.error instanceof Error
							? downloadAsrModelsMutation.error.message
							: (asrMissingModelRecovery?.message ?? null)
						: null
				}
				downloadPending={downloadAsrModelsMutation.isPending}
				failedStage={failedStage}
				onDownloadModels={() => {
					void downloadAsrModelsMutation.mutateAsync();
				}}
				onRetry={(stageName) => {
					void retryStageMutation.mutateAsync(stageName);
				}}
				retryErrorMessage={
					retryStageMutation.isError
						? retryStageMutation.error instanceof Error
							? retryStageMutation.error.message
							: TASK_DETAIL_COPY.failure.retryErrorFallback
						: null
				}
				retryPending={retryStageMutation.isPending}
				state={taskState}
				task={taskDetailQuery.data}
			/>

			{isActiveAsr && executionProgress?.stage_name === "asr" ? (
				<AsrExecutionProgressPanel
					executionProgress={executionProgress}
					taskStatus={taskDetailQuery.data.status}
				/>
			) : null}

			<div className="detail-grid">
				<section className="panel">
					<div className="panel__header">
						<div>
							<p className="eyebrow">{TASK_DETAIL_COPY.timeline.eyebrow}</p>
							<h3>{TASK_DETAIL_COPY.timeline.title}</h3>
						</div>
						<span className="pill">
							{isTerminalStatus(taskDetailQuery.data.status)
								? TASK_DETAIL_COPY.timeline.pollingTerminal
								: TASK_DETAIL_COPY.timeline.pollingActive}
						</span>
					</div>

					<ol className="stage-list">
						{stageRows.map((stage) => (
							<li className="stage-card" key={stage.name}>
								<div className="stage-card__header">
									<div>
										<p className="stage-card__eyebrow">
											{GLOSSARY_TERMS.stage}
										</p>
										<h4>{formatStageLabel(stage.name)}</h4>
									</div>
									<span className={getStatusTone(stage.status)}>
										{formatTaskStatusLabel(stage.status)}
									</span>
								</div>
								<p>{stage.summary}</p>
								<div className="stage-card__meta">
									<span>
										{TASK_DETAIL_COPY.timeline.attempts(stage.attempts)}
									</span>
									<span>
										{stage.displayLabel ?? TASK_DETAIL_COPY.timeline.noStageLog}
									</span>
								</div>
								{stage.logPath ? (
									<details className="log-path-disclosure">
										<summary>
											{TASK_DETAIL_COPY.timeline.technicalLogPath}
										</summary>
										<code>{stage.logPath}</code>
									</details>
								) : null}
							</li>
						))}
					</ol>
				</section>

				<section className="panel">
					<div className="panel__header">
						<div>
							<p className="eyebrow">{TASK_DETAIL_COPY.artifacts.eyebrow}</p>
							<h3>{TASK_DETAIL_COPY.artifacts.title}</h3>
						</div>
						<span className="pill">
							{TASK_DETAIL_COPY.artifacts.count(artifacts.length)}
						</span>
					</div>

					{artifacts.length > 0 ? (
						<div className="artifact-list">
							{artifacts.map((artifact) => (
								<ArtifactCard artifact={artifact} key={artifact.id} />
							))}
						</div>
					) : (
						<p className="support-copy">{TASK_DETAIL_COPY.artifacts.empty}</p>
					)}
				</section>
			</div>

			<WorkspacePage
				artifactReadiness={taskDetailQuery.data.artifact_readiness}
				artifacts={artifacts}
				taskId={taskId}
			/>
		</section>
	);
}
