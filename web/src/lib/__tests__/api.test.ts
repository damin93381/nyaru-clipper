import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadAsrModels, fetchArtifactJson, getRuntimeCapabilities } from "../api";

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
});
