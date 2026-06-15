import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import { fetchArtifactJson, getRuntimeCapabilities, getTaskDetail, getTaskLogs } from "../api";

describe("fetchArtifactJson", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves app-backed artifact paths against the API base URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ segments: [{ id: "seg-1" }] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchArtifactJson<{ segments: Array<{ id: string }> }>(
      "/api/tasks/task-workspace123/artifacts/1/content/asr-segments.json",
    );

    expect(payload).toEqual({ segments: [{ id: "seg-1" }] });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/tasks/task-workspace123/artifacts/1/content/asr-segments.json",
      {
        headers: {
          Accept: "application/json",
        },
      },
    );
  });

  it("uses the configured uv-first backend origin for runtime capabilities", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ok", detected_profile: "linux-cuda", warnings: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await getRuntimeCapabilities();

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/runtime/capabilities", {
      headers: {
        "Content-Type": "application/json",
      },
    });
  });

  it("posts requested ASR model keys to the task download endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ stage: "asr", kind: "missing_model", models: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const downloadAsrModels = Reflect.get(api, "downloadAsrModels");

    expect(downloadAsrModels).toBeTypeOf("function");

    if (typeof downloadAsrModels !== "function") {
      return;
    }

    await downloadAsrModels("task-models123", ["whisperx", "alignment"]);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/tasks/task-models123/asr/models/download",
      {
        method: "POST",
        body: JSON.stringify({ model_keys: ["whisperx", "alignment"] }),
        headers: {
          "Content-Type": "application/json",
        },
      },
    );
  });

  it("posts retry stage requests to the task retry endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ task_id: "task-retry123", retry_stage: "translation", status: "pending" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const retryTaskFromStage = Reflect.get(api, "retryTaskFromStage");

    expect(retryTaskFromStage).toBeTypeOf("function");

    if (typeof retryTaskFromStage !== "function") {
      return;
    }

    await retryTaskFromStage("task-retry123", "translation");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/tasks/task-retry123/retry",
      {
        method: "POST",
        body: JSON.stringify({ stage_name: "translation" }),
        headers: {
          "Content-Type": "application/json",
        },
      },
    );
  });

  it("accepts structured task recovery and readiness response fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        task_id: "task-recovery123",
        source_url: "https://www.bilibili.com/video/BV1recovery123",
        normalized_source_url: "https://www.bilibili.com/video/BV1recovery123",
        source_video_id: "BV1recovery123",
        status: "failed",
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
            endpoint: "/api/tasks/task-recovery123/asr/models/download",
            href: "/api/tasks/task-recovery123/asr/models/download",
            payload: { model_keys: ["whisperx", "alignment"] },
            confirmation_required: false,
            success_behavior: "retry_stage_after_success",
          },
        ],
        artifact_readiness: [
          {
            kind: "transcript_json",
            stage_name: "asr",
            status: "failed",
            artifact_id: null,
            path: null,
          },
        ],
        stages: [
          {
            name: "asr",
            status: "failed",
            summary: "missing_model",
            failure_code: "asr_missing_model",
            recovery_actions: [],
            attempts: 1,
          },
        ],
        failure_recovery: {
          stage: "asr",
          kind: "missing_model",
          message: "ASR 缺少 WhisperX 模型文件。",
          models: [],
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const detail = await getTaskDetail("task-recovery123");

    expect(detail.failure_code).toBe("asr_missing_model");
    expect(detail.recovery_actions?.[0]).toMatchObject({
      id: "download_asr_model",
      label_key: "download_asr_model",
      enabled: true,
      method: "POST",
    });
    expect(detail.artifact_readiness?.[0]).toMatchObject({
      kind: "transcript_json",
      stage_name: "asr",
      status: "failed",
    });
    expect(detail.stages[0]).toMatchObject({
      name: "asr",
      failure_code: "asr_missing_model",
    });
  });

  it("accepts safe log summaries without relying on raw log paths", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          stage_name: "translation",
          status: "failed",
          summary: "provider timed out with token abc123",
          display_label: "Translation",
          safe_summary: "provider timed out with token [redacted]",
          log_path: "/data/tasks/task-recovery123/logs/translation.log",
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const logs = await getTaskLogs("task-recovery123");

    expect(logs[0]).toMatchObject({
      display_label: "Translation",
      safe_summary: "provider timed out with token [redacted]",
    });
  });
});
