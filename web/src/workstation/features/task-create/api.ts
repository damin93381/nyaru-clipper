import type { components } from "../../../generated/api-schema";

import { workstationClient } from "../../api/client";

export type BilibiliInspection = components["schemas"]["BilibiliInspectionResponse"];
export type CreateTaskRequest = components["schemas"]["CreateWorkstationTaskRequest"];
export type CreateTaskResponse = components["schemas"]["CreateWorkstationTaskResponse"];
export type LocalDirectory = components["schemas"]["LocalDirectoryResponse"];
export type ProcessingProfile = components["schemas"]["ProcessingProfileResponse"];

type TaskCreateField = "priority" | "profile_id" | "source";

export class TaskCreateApiError extends Error {
  constructor(
    readonly action: string,
    readonly fieldErrors: Readonly<Partial<Record<TaskCreateField, string>>>,
  ) {
    super(action);
    this.name = "TaskCreateApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isTaskCreateField(value: unknown): value is TaskCreateField {
  return value === "source" || value === "profile_id" || value === "priority";
}

function fieldErrorsFrom(error: unknown): Readonly<Partial<Record<TaskCreateField, string>>> {
  if (!isRecord(error) || !Array.isArray(error.detail)) return {};
  return error.detail.reduce<Partial<Record<TaskCreateField, string>>>((errors, detail) => {
    if (!isRecord(detail) || !Array.isArray(detail.loc) || typeof detail.msg !== "string") return errors;
    const field = detail.loc.find(isTaskCreateField);
    if (field === undefined || errors[field] !== undefined) return errors;
    return { ...errors, [field]: detail.msg };
  }, {});
}

async function requireData<Result>(request: Promise<{ readonly data?: Result; readonly error?: unknown }>, action: string): Promise<Result> {
  const { data, error } = await request;
  if (data !== undefined) return data;
  throw new TaskCreateApiError(action, fieldErrorsFrom(error));
}

export function inspectBilibiliSource(url: string): Promise<BilibiliInspection> {
  return requireData(
    workstationClient.POST("/api/v2/sources/bilibili/inspect", { body: { url }, parseAs: "json" }),
    "来源检查失败，请确认链接后重试。",
  );
}

export function getLocalDirectory(rootId?: string, relativePath?: string): Promise<LocalDirectory> {
  const query = rootId === undefined ? undefined : { relative_path: relativePath ?? "", root_id: rootId };
  return requireData(
    workstationClient.GET("/api/v2/sources/local", { params: query === undefined ? undefined : { query }, parseAs: "json" }),
    "本地媒体目录暂时不可读取。",
  );
}

export function getProcessingProfiles(): Promise<readonly ProcessingProfile[]> {
  return requireData(
    workstationClient.GET("/api/v2/processing-profiles", { parseAs: "json" }),
    "处理配置暂时不可读取。",
  ).then((response) => response.profiles);
}

export function createWorkstationTask(request: CreateTaskRequest): Promise<CreateTaskResponse> {
  return requireData(
    workstationClient.POST("/api/v2/tasks", { body: request, parseAs: "json" }),
    "任务没有创建，请重试。",
  );
}
