import type {
  DownloadAsrModelsPayload,
  DownloadAsrModelsResponse,
  ArtifactRecord,
  AsrMissingModelKey,
  ClipExportPayload,
  ClipExportResponse,
  CreateTaskPayload,
  RuntimeCapabilities,
  StageLogSummary,
  TaskDetail,
  TaskStageRecord,
} from "./types";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api";

function getApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined;
  return (configured || DEFAULT_API_BASE_URL).replace(/\/$/, "");
}

function resolveArtifactUrl(path: string): string {
  if (/^https?:\/\//.test(path)) {
    return path;
  }

  return new URL(path, `${getApiBaseUrl()}/`).toString();
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;

    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        message = payload.detail;
      }
    } catch {
      // Keep the fallback message.
    }

    throw new ApiError(message, response.status);
  }

  return response.json() as Promise<T>;
}

export function createTask(payload: CreateTaskPayload): Promise<TaskDetail> {
  return request<TaskDetail>("/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getTaskDetail(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>(`/tasks/${taskId}`);
}

export function getTaskStages(taskId: string): Promise<TaskStageRecord[]> {
  return request<TaskStageRecord[]>(`/tasks/${taskId}/stages`);
}

export function getTaskArtifacts(taskId: string): Promise<ArtifactRecord[]> {
  return request<ArtifactRecord[]>(`/tasks/${taskId}/artifacts`);
}

export function getTaskLogs(taskId: string): Promise<StageLogSummary[]> {
  return request<StageLogSummary[]>(`/tasks/${taskId}/logs`);
}

export function exportTaskClip(taskId: string, payload: ClipExportPayload): Promise<ClipExportResponse> {
  return request<ClipExportResponse>(`/tasks/${taskId}/clips`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function downloadAsrModels(
  taskId: string,
  modelKeys: AsrMissingModelKey[],
): Promise<DownloadAsrModelsResponse> {
  const payload: DownloadAsrModelsPayload = {
    model_keys: modelKeys,
  };

  return request<DownloadAsrModelsResponse>(
    `/tasks/${taskId}/asr/models/download`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function getRuntimeCapabilities(): Promise<RuntimeCapabilities> {
  return request<RuntimeCapabilities>("/runtime/capabilities");
}
export async function fetchArtifactJson<T>(path: string): Promise<T> {
  const response = await fetch(resolveArtifactUrl(path), {
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Artifact request failed with status ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export { resolveArtifactUrl };
