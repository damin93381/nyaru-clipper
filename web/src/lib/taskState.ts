import type {
  ArtifactReadinessRecord,
  ArtifactReadinessStatus,
  TaskDetail,
  TaskRecoveryAction,
  TaskStageName,
  TaskStageRecord,
} from "./types";

export type LoadErrorState = {
  kind: "artifact_load_error" | "log_load_error";
};

export type TaskStateInput = TaskDetail | LoadErrorState | null | undefined;

export type TaskState =
  | "new_task"
  | "queued"
  | "active"
  | "failed_retryable"
  | "failed_asr_missing_model"
  | "failed_terminal"
  | "artifact_not_ready"
  | "artifact_missing"
  | "artifact_failed"
  | "artifact_load_error"
  | "log_not_ready"
  | "log_load_error"
  | "cancelled"
  | "force_kill_requested"
  | "retry_in_progress"
  | "worker_stale_recovery"
  | "not_found"
  | "success"
  | "unknown";

export type TaskPrimaryAction =
  | "create_task"
  | "wait"
  | "cancel"
  | "retry_stage"
  | "download_asr_model"
  | "view_recovery"
  | "retry_loading_section"
  | "retry_logs"
  | "start_new_task"
  | "wait_for_worker"
  | "back_to_new_task"
  | "view_logs"
  | "none";

export type ArtifactReadinessClassification = ArtifactReadinessStatus | "load_error";

function isLoadErrorState(input: TaskStateInput): input is LoadErrorState {
  return Boolean(
    input &&
      typeof input === "object" &&
      "kind" in input &&
      (input.kind === "artifact_load_error" || input.kind === "log_load_error"),
  );
}

function getFailedStage(task: TaskDetail): TaskStageRecord | undefined {
  return task.stages.find((stage) => stage.status === "failed");
}

function getTaskFailureCode(task: TaskDetail): string | null {
  return task.failure_code ?? getFailedStage(task)?.failure_code ?? null;
}

function getActions(task: TaskDetail, stage?: TaskStageRecord): TaskRecoveryAction[] {
  return [...(task.recovery_actions ?? []), ...(stage?.recovery_actions ?? [])];
}

function getActionStageName(action: TaskRecoveryAction): string | null {
  const payloadStage = action.payload?.stage_name;
  return typeof payloadStage === "string" ? payloadStage : null;
}

function hasEnabledAction(
  task: TaskDetail,
  actionId: string,
  stage?: TaskStageRecord,
): boolean {
  return getActions(task, stage).some((action) => {
    if (action.id !== actionId || !action.enabled) {
      return false;
    }

    const targetStageName = getActionStageName(action);
    return !stage || targetStageName === null || targetStageName === stage.name;
  });
}

function firstBlockingReadiness(
  readiness: ArtifactReadinessRecord[] | undefined,
): ArtifactReadinessRecord | undefined {
  return readiness?.find((item) => item.status !== "ready");
}

function hasPendingLog(task: TaskDetail): boolean {
  return Boolean(
    task.log_records?.some(
      (log) =>
        log.status === "pending" &&
        !log.summary &&
        !log.safe_summary,
    ),
  );
}

function isRetryInProgress(task: TaskDetail): boolean {
  return (
    task.status === "pending" &&
    task.stages.some((stage) => stage.attempts > 0 && stage.status === "pending")
  );
}

function hasActiveStage(task: TaskDetail): boolean {
  return (
    task.status === "running" ||
    task.status === "cancel_requested" ||
    task.stages.some((stage) => stage.status === "running")
  );
}

export function classifyTaskState(input: TaskStateInput): TaskState {
  if (input === undefined) {
    return "new_task";
  }

  if (input === null) {
    return "not_found";
  }

  if (isLoadErrorState(input)) {
    return input.kind;
  }

  if (input.execution_control?.force_kill_requested) {
    return "force_kill_requested";
  }

  if (input.status === "cancelled") {
    return "cancelled";
  }

  const failedStage = getFailedStage(input);
  const failureCode = getTaskFailureCode(input);

  if (failureCode === "asr_missing_model") {
    return "failed_asr_missing_model";
  }

  if (failureCode === "stale_job_recovered") {
    return "worker_stale_recovery";
  }

  const blockingReadiness = firstBlockingReadiness(input.artifact_readiness);
  if (blockingReadiness?.status === "failed" && !hasEnabledAction(input, "retry_stage", failedStage)) {
    return "artifact_failed";
  }
  if (blockingReadiness?.status === "missing") {
    return "artifact_missing";
  }
  if (blockingReadiness?.status === "not_ready") {
    return "artifact_not_ready";
  }

  if (hasPendingLog(input)) {
    return "log_not_ready";
  }

  if (input.status === "failed") {
    if (failedStage && hasEnabledAction(input, "retry_stage", failedStage)) {
      return "failed_retryable";
    }
    return "failed_terminal";
  }

  if (hasActiveStage(input)) {
    return "active";
  }

  if (isRetryInProgress(input)) {
    return "retry_in_progress";
  }

  if (input.status === "pending") {
    return "queued";
  }

  if (input.status === "success") {
    return "success";
  }

  return "unknown";
}

export function getPrimaryAction(state: TaskState): TaskPrimaryAction {
  switch (state) {
    case "new_task":
      return "create_task";
    case "queued":
    case "artifact_not_ready":
    case "log_not_ready":
    case "retry_in_progress":
      return "wait";
    case "active":
      return "cancel";
    case "failed_asr_missing_model":
      return "download_asr_model";
    case "failed_retryable":
    case "artifact_missing":
    case "worker_stale_recovery":
      return "retry_stage";
    case "artifact_failed":
      return "view_recovery";
    case "artifact_load_error":
      return "retry_loading_section";
    case "log_load_error":
      return "retry_logs";
    case "cancelled":
      return "start_new_task";
    case "force_kill_requested":
      return "wait_for_worker";
    case "not_found":
      return "back_to_new_task";
    case "failed_terminal":
      return "view_logs";
    case "success":
    case "unknown":
      return "none";
  }
}

export function classifyArtifactReadiness(
  readiness: ArtifactReadinessStatus | "load_error",
): ArtifactReadinessClassification {
  return readiness;
}

export function isRetryable(task: TaskDetail, stageName: TaskStageName): boolean {
  const stage = task.stages.find((item) => item.name === stageName);
  if (!stage || stage.status !== "failed") {
    return false;
  }

  return hasEnabledAction(task, "retry_stage", stage);
}
