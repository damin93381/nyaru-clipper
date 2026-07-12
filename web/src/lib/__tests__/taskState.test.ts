import { describe, expect, it } from "vitest";

import {
  classifyArtifactReadiness,
  classifyTaskState,
  getPrimaryAction,
  isRetryable,
} from "../taskState";
import type {
  ArtifactReadinessStatus,
  TaskDetail,
  TaskStageName,
  TaskStageRecord,
  TaskStatus,
} from "../types";

const stageNames: TaskStageName[] = [
  "ingest",
  "media_prep",
  "asr",
  "translation",
  "highlight",
  "export",
  "report",
];

function stagesWith(
  overrides: Partial<Record<TaskStageName, Partial<TaskStageRecord>>> = {},
): TaskStageRecord[] {
  return stageNames.map((name) => ({
    name,
    status: "pending",
    summary: null,
    failure_code: null,
    recovery_actions: [],
    attempts: 0,
    ...overrides[name],
  }));
}

function task(
  status: TaskStatus,
  overrides: Partial<TaskDetail> = {},
): TaskDetail {
  return {
    task_id: "task-state123",
    source_url: "https://www.bilibili.com/video/BV1state123",
    normalized_source_url: "https://www.bilibili.com/video/BV1state123",
    source_video_id: "BV1state123",
    status,
    failure_code: null,
    recovery_actions: [],
    artifact_readiness: [],
    stages: stagesWith(),
    ...overrides,
  };
}

describe("classifyTaskState", () => {
  it.each([
    {
      label: "new task / no task",
      task: undefined,
      state: "new_task",
      action: "create_task",
    },
    {
      label: "queued",
      task: task("pending"),
      state: "queued",
      action: "wait",
    },
    {
      label: "active stage",
      task: task("running", {
        stages: stagesWith({ asr: { status: "running", attempts: 1 } }),
      }),
      state: "active",
      action: "cancel",
    },
    {
      label: "stage failed generic",
      task: task("failed", {
        failure_code: "unknown_failure",
        recovery_actions: [
          {
            id: "retry_stage",
            label: "Retry translation",
            label_key: "retry_stage",
            description_key: "retry_stage",
            enabled: true,
            disabled_reason: null,
            method: "POST",
            endpoint: "/api/tasks/task-state123/retry",
            href: "/api/tasks/task-state123/retry",
            payload: { stage_name: "translation" },
            confirmation_required: false,
            success_behavior: "poll_task",
          },
        ],
        stages: stagesWith({
          ingest: { status: "success", attempts: 1 },
          media_prep: { status: "success", attempts: 1 },
          asr: { status: "success", attempts: 1 },
          translation: {
            status: "failed",
            attempts: 2,
            failure_code: "unknown_failure",
          },
        }),
      }),
      state: "failed_retryable",
      action: "retry_stage",
    },
    {
      label: "ASR missing model",
      task: task("failed", {
        failure_code: "asr_missing_model",
        recovery_actions: [
          {
            id: "download_asr_model",
            label: "Download missing ASR models",
            label_key: "download_asr_model",
            description_key: "download_asr_model",
            enabled: true,
            disabled_reason: null,
            method: "POST",
            endpoint: "/api/tasks/task-state123/asr/models/download",
            href: "/api/tasks/task-state123/asr/models/download",
            payload: { model_keys: ["whisperx", "alignment"] },
            confirmation_required: false,
            success_behavior: "retry_stage_after_success",
          },
        ],
        stages: stagesWith({
          ingest: { status: "success", attempts: 1 },
          media_prep: { status: "success", attempts: 1 },
          asr: {
            status: "failed",
            attempts: 1,
            failure_code: "asr_missing_model",
          },
        }),
      }),
      state: "failed_asr_missing_model",
      action: "download_asr_model",
    },
    {
      label: "artifact load error",
      task: { kind: "artifact_load_error" as const },
      state: "artifact_load_error",
      action: "retry_loading_section",
    },
    {
      label: "artifact not ready",
      task: task("running", {
        artifact_readiness: [
          { kind: "transcript_json", stage_name: "asr", status: "not_ready", artifact_id: null, path: null },
        ],
      }),
      state: "artifact_not_ready",
      action: "wait",
    },
    {
      label: "artifact missing",
      task: task("success", {
        artifact_readiness: [
          { kind: "transcript_json", stage_name: "asr", status: "missing", artifact_id: null, path: null },
        ],
      }),
      state: "artifact_missing",
      action: "retry_stage",
    },
    {
      label: "failed task with retry action wins over artifact missing",
      task: task("failed", {
        failure_code: "unknown_failure",
        recovery_actions: [
          {
            id: "retry_stage",
            label: "Retry translation",
            label_key: "retry_stage",
            description_key: "retry_stage",
            enabled: true,
            disabled_reason: null,
            method: "POST",
            endpoint: "/api/tasks/task-state123/retry",
            href: "/api/tasks/task-state123/retry",
            payload: { stage_name: "translation" },
            confirmation_required: false,
            success_behavior: "poll_task",
          },
        ],
        stages: stagesWith({
          ingest: { status: "success", attempts: 1 },
          media_prep: { status: "success", attempts: 1 },
          asr: { status: "success", attempts: 1 },
          translation: { status: "failed", attempts: 2, failure_code: "unknown_failure" },
        }),
        artifact_readiness: [
          { kind: "translated_segments", stage_name: "translation", status: "missing", artifact_id: null, path: null },
        ],
      }),
      state: "failed_retryable",
      action: "retry_stage",
    },
    {
      label: "artifact failed",
      task: task("failed", {
        failure_code: "unknown_failure",
        artifact_readiness: [
          { kind: "translated_segments", stage_name: "translation", status: "failed", artifact_id: null, path: null },
        ],
      }),
      state: "artifact_failed",
      action: "view_recovery",
    },
    {
      label: "log not ready",
      task: task("pending", {
        log_records: [
          {
            stage_name: "asr",
            status: "pending",
            summary: null,
            display_label: "ASR",
            safe_summary: null,
            log_path: "/data/tasks/task-state123/logs/asr.log",
          },
        ],
      }),
      state: "log_not_ready",
      action: "wait",
    },
    {
      label: "log load error",
      task: { kind: "log_load_error" as const },
      state: "log_load_error",
      action: "retry_logs",
    },
    {
      label: "cancelled",
      task: task("cancelled"),
      state: "cancelled",
      action: "start_new_task",
    },
    {
      label: "force-kill requested",
      task: task("cancel_requested", {
        execution_control: { force_kill_requested: true },
      }),
      state: "force_kill_requested",
      action: "wait_for_worker",
    },
    {
      label: "retry in progress",
      task: task("pending", {
        stages: stagesWith({ translation: { status: "pending", attempts: 2 } }),
      }),
      state: "retry_in_progress",
      action: "wait",
    },
    {
      label: "worker stale recovery",
      task: task("failed", {
        failure_code: "stale_job_recovered",
        stages: stagesWith({ asr: { status: "failed", attempts: 1, failure_code: "stale_job_recovered" } }),
        recovery_actions: [
          {
            id: "retry_stage",
            label: "Retry asr",
            label_key: "retry_stage",
            description_key: "retry_stage",
            enabled: true,
            disabled_reason: null,
            method: "POST",
            endpoint: "/api/tasks/task-state123/retry",
            href: "/api/tasks/task-state123/retry",
            payload: { stage_name: "asr" },
            confirmation_required: false,
            success_behavior: "poll_task",
          },
        ],
      }),
      state: "worker_stale_recovery",
      action: "retry_stage",
    },
    {
      label: "task not found",
      task: null,
      state: "not_found",
      action: "back_to_new_task",
    },
  ])("classifies $label", ({ task: taskValue, state, action }) => {
    const classified = classifyTaskState(taskValue);

    expect(classified).toBe(state);
    expect(getPrimaryAction(classified)).toBe(action);
  });
});

describe("classifyArtifactReadiness", () => {
  it.each([
    ["ready", "ready"],
    ["not_ready", "not_ready"],
    ["missing", "missing"],
    ["failed", "failed"],
    ["load_error", "load_error"],
  ] satisfies Array<[ArtifactReadinessStatus | "load_error", string]>) (
    "returns %s readiness classification",
    (readiness, expected) => {
      expect(classifyArtifactReadiness(readiness)).toBe(expected);
    },
  );
});

describe("isRetryable", () => {
  it("uses recovery actions instead of parsing human summaries", () => {
    const retryableTask = task("failed", {
      stages: stagesWith({ translation: { status: "failed", attempts: 2, failure_code: "unknown_failure" } }),
      recovery_actions: [
        {
          id: "retry_stage",
          label: "Retry translation",
          label_key: "retry_stage",
          description_key: "retry_stage",
          enabled: true,
          disabled_reason: null,
          method: "POST",
          endpoint: "/api/tasks/task-state123/retry",
          href: "/api/tasks/task-state123/retry",
          payload: { stage_name: "translation" },
          confirmation_required: false,
          success_behavior: "poll_task",
        },
      ],
    });

    expect(isRetryable(retryableTask, "translation")).toBe(true);
    expect(isRetryable({ ...retryableTask, recovery_actions: [] }, "translation")).toBe(false);
  });
});
