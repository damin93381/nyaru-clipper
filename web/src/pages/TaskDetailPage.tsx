import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useParams } from "react-router-dom";

import {
	getTaskArtifacts,
	getTaskDetail,
	getTaskLogs,
	getTaskStages,
} from "../lib/api";
import { GLOSSARY_TERMS } from "../lib/copy/glossary";
import { TASK_DETAIL_COPY } from "../lib/copy/taskDetail";
import {
	type ArtifactRecord,
	CANONICAL_STAGES,
	formatStageLabel,
	formatTaskStatusLabel,
	humanizeSummary,
	isTerminalStatus,
	type StageLogSummary,
	safeParseMetadata,
	type TaskStageRecord,
	type TaskStatus,
} from "../lib/types";
import { WorkspacePage } from "./WorkspacePage";

interface StageRow {
	name: string;
	status: TaskStatus;
	attempts: number;
	summary: string;
	logPath: string | null;
}

export function getPollingInterval(
	status: TaskStatus | null | undefined,
): number {
	return isTerminalStatus(status) ? 15_000 : 3_000;
}

function getStatusTone(status: TaskStatus): string {
	return `status-badge status-badge--${status}`;
}

function buildStageRows(
	stages: TaskStageRecord[],
	logs: StageLogSummary[],
): StageRow[] {
	const stagesByName = new Map(stages.map((stage) => [stage.name, stage]));
	const logsByStage = new Map(logs.map((log) => [log.stage_name, log]));

	return CANONICAL_STAGES.map((stageName) => {
		const stage = stagesByName.get(stageName);
		const log = logsByStage.get(stageName);
		const rawSummary = log?.summary ?? stage?.summary ?? null;

		return {
			name: stageName,
			status: stage?.status ?? log?.status ?? "pending",
			attempts: stage?.attempts ?? 0,
			summary: humanizeSummary(rawSummary),
			logPath: log?.log_path ?? null,
		};
	});
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

export function TaskDetailPage() {
	const params = useParams();
	const taskId = params.taskId ?? "";

	const taskDetailQuery = useQuery({
		queryKey: ["task", taskId, "detail"],
		queryFn: () => getTaskDetail(taskId),
		enabled: Boolean(taskId),
		refetchInterval: (query) => getPollingInterval(query.state.data?.status),
	});

	const taskStatus = taskDetailQuery.data?.status;

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

	const stages = stageQuery.data ?? taskDetailQuery.data?.stages ?? [];
	const logs = logsQuery.data ?? [];
	const artifacts = artifactsQuery.data ?? [];

	const stageRows = useMemo(() => buildStageRows(stages, logs), [logs, stages]);
	const failedStage =
		stageRows.find((stage) => stage.status === "failed") ?? null;

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

			{failedStage ? (
				<div className="panel panel--danger">
					<p className="eyebrow">{TASK_DETAIL_COPY.failure.eyebrow}</p>
					<h3>
						{TASK_DETAIL_COPY.failure.title(formatStageLabel(failedStage.name))}
					</h3>
					<p>{failedStage.summary}</p>
					<p>
						{TASK_DETAIL_COPY.failure.recovery(
							formatStageLabel(failedStage.name),
						)}
					</p>
				</div>
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
									{stage.logPath ? (
										<span>{stage.logPath}</span>
									) : (
										<span>{TASK_DETAIL_COPY.timeline.noStageLog}</span>
									)}
								</div>
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

			<WorkspacePage artifacts={artifacts} taskId={taskId} />
		</section>
	);
}
