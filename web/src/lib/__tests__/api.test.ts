import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchArtifactJson } from "../api";

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
});
