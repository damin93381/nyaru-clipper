import type { WorkstationTaskListFilters } from "../../api/queryKeys";

const taskStatuses = ["pending", "running", "success", "failed", "cancelled"] as const;
const taskSorts = ["updated_at", "created_at", "title", "storage_bytes"] as const;
const taskDirections = ["asc", "desc"] as const;
const taskPageSizes = [25, 50, 100] as const;

type TaskStatus = (typeof taskStatuses)[number];
type TaskSort = (typeof taskSorts)[number];
type TaskDirection = (typeof taskDirections)[number];

export interface TaskLibraryFilters {
  readonly query: string;
  readonly statuses: readonly TaskStatus[];
  readonly sourceKind: "all" | "bilibili" | "local";
  readonly tag: string | null;
  readonly sort: TaskSort;
  readonly direction: TaskDirection;
  readonly page: number;
  readonly pageSize: (typeof taskPageSizes)[number];
}

const defaultFilters: TaskLibraryFilters = {
  query: "",
  statuses: [],
  sourceKind: "all",
  tag: null,
  sort: "updated_at",
  direction: "desc",
  page: 1,
  pageSize: 50,
};

function isTaskStatus(value: string): value is TaskStatus {
  return taskStatuses.some((status) => status === value);
}

function isTaskSort(value: string | null): value is TaskSort {
  return taskSorts.some((sort) => sort === value);
}

function isTaskDirection(value: string | null): value is TaskDirection {
  return taskDirections.some((direction) => direction === value);
}

function parsePageSize(value: string | null): TaskLibraryFilters["pageSize"] {
  if (value === "25") return 25;
  if (value === "100") return 100;
  return 50;
}

function parsePositiveInteger(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function parseTaskLibraryFilters(params: URLSearchParams): TaskLibraryFilters {
  const statuses = params.getAll("status").filter(isTaskStatus);
  const source = params.get("source");
  const sort = params.get("sort");
  const direction = params.get("direction");
  const pageSize = params.get("pageSize");
  const query = params.get("query")?.trim() ?? "";
  const tag = params.get("tag")?.trim() || null;

  return {
    query,
    statuses,
    sourceKind: source === "bilibili" || source === "local" ? source : defaultFilters.sourceKind,
    tag,
    sort: isTaskSort(sort) ? sort : defaultFilters.sort,
    direction: isTaskDirection(direction) ? direction : defaultFilters.direction,
    page: parsePositiveInteger(params.get("page"), defaultFilters.page),
    pageSize: parsePageSize(pageSize),
  };
}

export function serializeTaskLibraryFilters(filters: TaskLibraryFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.query) params.set("query", filters.query);
  for (const status of filters.statuses) params.append("status", status);
  if (filters.sourceKind !== "all") params.set("source", filters.sourceKind);
  if (filters.tag) params.set("tag", filters.tag);
  if (filters.sort !== defaultFilters.sort) params.set("sort", filters.sort);
  if (filters.direction !== defaultFilters.direction) params.set("direction", filters.direction);
  if (filters.page !== defaultFilters.page) params.set("page", String(filters.page));
  if (filters.pageSize !== defaultFilters.pageSize) params.set("pageSize", String(filters.pageSize));
  return params;
}

export function toTaskListQuery(filters: TaskLibraryFilters): WorkstationTaskListFilters {
  return {
    query: filters.query || undefined,
    statuses: filters.statuses.length > 0 ? [...filters.statuses] : undefined,
    source_kind: filters.sourceKind === "all" ? undefined : filters.sourceKind,
    tag: filters.tag,
    sort: filters.sort,
    direction: filters.direction,
    page: filters.page,
    page_size: filters.pageSize,
  };
}
