import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import {
  downloadAsrModels,
  getTaskArtifacts,
  getTaskDetail,
  getTaskLogs,
  getTaskStages,
} from "../lib/api";
import {
  CANONICAL_STAGES,
  formatStageLabel,
  humanizeSummary,
  isTerminalStatus,
  safeParseMetadata,
  type AsrMissingModelRecovery,
  type ArtifactRecord,
  type StageLogSummary,
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

export function getPollingInterval(status: TaskStatus | null | undefined): number {
  return isTerminalStatus(status) ? 15_000 : 3_000;
}

function getStatusTone(status: TaskStatus): string {
  return `status-badge status-badge--${status}`;
}

function buildStageRows(stages: TaskStageRecord[], logs: StageLogSummary[]): StageRow[] {
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

function flattenMetadata(metadata: Record<string, unknown>, prefix = ""): Array<[string, string]> {
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
  const metadataEntries = flattenMetadata(safeParseMetadata(artifact.metadata_json));

  return (
    <article className="artifact-card">
      <div className="artifact-card__header">
        <strong>{artifact.kind}</strong>
        <span className="status-badge status-badge--success">{formatStageLabel(artifact.stage_name)}</span>
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
        <p className="support-copy">No metadata available for this artifact.</p>
      )}
    </article>
  );
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
  const failedStage = stageRows.find((stage) => stage.status === "failed") ?? null;
  const failureRecovery = taskDetailQuery.data?.failure_recovery;
  const asrMissingModelRecovery: AsrMissingModelRecovery | null =
    failureRecovery?.stage === "asr" && failureRecovery.kind === "missing_model"
      ? failureRecovery
      : null;
  const downloadableModelKeys =
    asrMissingModelRecovery?.models
      .filter((model) => model.download_supported && model.status === "missing")
      .map((model) => model.key) ?? [];

  const downloadAsrModelsMutation = useMutation({
    mutationFn: () => downloadAsrModels(taskId, downloadableModelKeys),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["task", taskId, "detail"] }),
        queryClient.invalidateQueries({ queryKey: ["task", taskId, "stages"] }),
        queryClient.invalidateQueries({ queryKey: ["task", taskId, "logs"] }),
      ]);
    },
  });

  if (taskDetailQuery.isPending && !taskDetailQuery.data) {
    return (
      <section className="page">
        <div className="panel panel--loading">
          <p className="eyebrow">Loading task</p>
          <h2>Fetching task detail...</h2>
        </div>
      </section>
    );
  }

  if (taskDetailQuery.isError || !taskDetailQuery.data) {
    return (
      <section className="page">
        <div className="panel panel--danger">
          <p className="eyebrow">Task unavailable</p>
          <h2>We couldn&apos;t load this task.</h2>
          <p>{taskDetailQuery.error instanceof Error ? taskDetailQuery.error.message : "Unknown error"}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="page detail-page">
      <div className="panel task-summary">
        <div>
          <p className="eyebrow">Task detail</p>
          <h2>{`Task ${taskDetailQuery.data.task_id}`}</h2>
          <p className="support-copy">{taskDetailQuery.data.normalized_source_url}</p>
        </div>
        <div className="task-summary__badges">
          <span className={getStatusTone(taskDetailQuery.data.status)}>{taskDetailQuery.data.status}</span>
          {taskDetailQuery.data.source_video_id ? <span className="pill">{taskDetailQuery.data.source_video_id}</span> : null}
        </div>
      </div>

      {failedStage ? (
        <div className="panel panel--danger">
          <p className="eyebrow">Readable failure summary</p>
          <h3>{`${formatStageLabel(failedStage.name)} stage failed`}</h3>
          <p>{failedStage.summary}</p>
          <p>{`Retry-ready from ${failedStage.name}. Upstream successes remain intact while downstream stages wait.`}</p>
          {asrMissingModelRecovery ? (
            <>
              <p className="eyebrow">ASR model recovery</p>
              <h4>Missing model handling</h4>
              <p>{asrMissingModelRecovery.message}</p>
              <p className="support-copy">
                You can place the required model files in the directories below, then rerun the ASR stage.
              </p>
              <dl className="metadata-list">
                {asrMissingModelRecovery.models.map((model) => (
                  <div className="metadata-list__row" key={model.key}>
                    <dt>{model.label}</dt>
                    <dd>{model.target_dir}</dd>
                  </div>
                ))}
              </dl>
              <button
                className="primary-button"
                disabled={downloadableModelKeys.length === 0 || downloadAsrModelsMutation.isPending}
                onClick={() => {
                  void downloadAsrModelsMutation.mutateAsync();
                }}
                type="button"
              >
                {downloadAsrModelsMutation.isPending
                  ? "Downloading missing ASR models..."
                  : "Download missing ASR models"}
              </button>
              {downloadAsrModelsMutation.isError ? (
                <p className="form-error">
                  {downloadAsrModelsMutation.error instanceof Error
                    ? downloadAsrModelsMutation.error.message
                    : asrMissingModelRecovery.message}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      <div className="detail-grid">
        <section className="panel">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Canonical pipeline</p>
              <h3>Stage timeline</h3>
            </div>
            <span className="pill">{isTerminalStatus(taskDetailQuery.data.status) ? "Polling every 15s" : "Polling every 3s"}</span>
          </div>

          <ol className="stage-list">
            {stageRows.map((stage) => (
              <li className="stage-card" key={stage.name}>
                <div className="stage-card__header">
                  <div>
                    <p className="stage-card__eyebrow">{formatStageLabel(stage.name)}</p>
                    <h4>{stage.name}</h4>
                  </div>
                  <span className={getStatusTone(stage.status)}>{stage.status}</span>
                </div>
                <p>{stage.summary}</p>
                <div className="stage-card__meta">
                  <span>{`Attempts: ${stage.attempts}`}</span>
                  {stage.logPath ? <span>{stage.logPath}</span> : <span>No stage log yet</span>}
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="panel">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Artifacts</p>
              <h3>Artifact overview</h3>
            </div>
            <span className="pill">{`${artifacts.length} item${artifacts.length === 1 ? "" : "s"}`}</span>
          </div>

          {artifacts.length > 0 ? (
            <div className="artifact-list">
              {artifacts.map((artifact) => (
                <ArtifactCard artifact={artifact} key={artifact.id} />
              ))}
            </div>
          ) : (
            <p className="support-copy">Artifacts appear here as stages persist durable outputs to the task tree.</p>
          )}
        </section>
      </div>

      <WorkspacePage artifacts={artifacts} taskId={taskId} />
    </section>
  );
}
