import * as Dialog from "@radix-ui/react-dialog";
import { Archive, ChevronLeft, ChevronRight, RotateCcw, RotateCw, Search, Tags, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { ReactNode } from "react";

import { getTaskLibraryPage, getTaskLibrarySummary, mutateTasks } from "./api";
import { parseTaskLibraryFilters, serializeTaskLibraryFilters, toTaskListQuery } from "./filters";
import { TaskTable } from "./TaskTable";
import { workstationKeys } from "../../api/queryKeys";
import type { TaskLibraryFilters } from "./filters";

const statusOptions = [
  ["pending", "待处理"],
  ["running", "运行中"],
  ["success", "已完成"],
  ["failed", "已失败"],
  ["cancelled", "已取消"],
] as const;

type BulkOperation = "archive" | "delete" | "set_tags" | "requeue";

function sourceKindFromInput(value: string): "all" | "bilibili" | "local" {
  if (value === "bilibili" || value === "local") return value;
  return "all";
}

function pageSizeFromInput(value: string): 25 | 50 | 100 {
  if (value === "25") return 25;
  if (value === "100") return 100;
  return 50;
}

function readinessFromInput(value: string): TaskLibraryFilters["readiness"] {
  if (value === "ready" || value === "missing" || value === "failed" || value === "not_ready") return value;
  return null;
}

function formatStorage(bytes: number): string {
  return `${(bytes / 1_024).toFixed(bytes >= 1_024 ? 1 : 0)} KB`;
}

function parseBulkTags(value: string): string[] {
  return value.split("，").map((tag) => tag.trim()).filter(Boolean);
}

function bulkOperationCopy(operation: BulkOperation): { readonly confirmLabel: string; readonly description: string; readonly title: string } {
  switch (operation) {
    case "archive":
      return { confirmLabel: "确认归档", description: "此操作会逐项执行，并保留未成功任务的选择状态。", title: "归档选中的任务？" };
    case "delete":
      return { confirmLabel: "确认删除", description: "此操作会逐项执行，并保留未成功任务的选择状态。", title: "删除选中的任务？" };
    case "set_tags":
      return { confirmLabel: "确认标记", description: "新标签会替换选中任务的现有标签，并保留未成功任务的选择状态。", title: "标记选中的任务？" };
    case "requeue":
      return { confirmLabel: "确认重新排队", description: "终止的任务会从中断阶段重新进入队列；未成功任务会保持选择状态。", title: "重新排队选中的任务？" };
  }
}

function summaryItems(summary: { readonly active: number; readonly archived: number; readonly queued: number; readonly failed: number; readonly review_required: number; readonly storage_bytes: number }): readonly string[] {
  return [
    `运行中 ${summary.active}`,
    `队列中 ${summary.queued}`,
    `失败 ${summary.failed}`,
    `待复核 ${summary.review_required}`,
    `已归档 ${summary.archived}`,
    `存储 ${formatStorage(summary.storage_bytes)}`,
  ];
}

export function TaskLibraryPage(): ReactNode {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseTaskLibraryFilters(searchParams), [searchParams]);
  const [searchInput, setSearchInput] = useState(filters.query);
  const [tagInput, setTagInput] = useState(filters.tag ?? "");
  const [selectedTaskIds, setSelectedTaskIds] = useState<ReadonlySet<string>>(() => new Set());
  const [bulkOperation, setBulkOperation] = useState<BulkOperation | null>(null);
  const [bulkTags, setBulkTags] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const inspectedTaskId = searchParams.get("selected");
  const summaryQuery = useQuery({ queryKey: workstationKeys.summary, queryFn: getTaskLibrarySummary });
  const taskQuery = useQuery({ queryKey: workstationKeys.list(toTaskListQuery(filters)), queryFn: () => getTaskLibraryPage(filters), placeholderData: (previous) => previous });
  const bulkMutation = useMutation({
    mutationFn: ({ operation, tags }: { readonly operation: BulkOperation; readonly tags?: readonly string[] }) => mutateTasks(operation, [...selectedTaskIds], tags),
    onSuccess: (response) => {
      const failedTaskIds = new Set(response.results.filter((result) => result.status !== "success").map((result) => result.task_id));
      setSelectedTaskIds(failedTaskIds);
      setAnnouncement(response.results.map((result) => `${result.task_id}：${result.message ?? (result.status === "success" ? "已完成" : "未完成")}`).join("；"));
      void queryClient.invalidateQueries({ queryKey: ["workstation", "tasks"] });
    },
    onError: () => setAnnouncement("批量操作未完成，请重试。"),
  });

  function replaceFilters(next: ReturnType<typeof parseTaskLibraryFilters>): void {
    const nextParams = serializeTaskLibraryFilters(next);
    if (inspectedTaskId) nextParams.set("selected", inspectedTaskId);
    setSearchParams(nextParams, { replace: true });
  }

  useEffect(() => setSearchInput(filters.query), [filters.query]);
  useEffect(() => setTagInput(filters.tag ?? ""), [filters.tag]);
  useEffect(() => {
    if (searchInput === filters.query) return undefined;
    const timer = window.setTimeout(() => replaceFilters({ ...filters, query: searchInput.trim(), page: 1 }), 250);
    return () => window.clearTimeout(timer);
  }, [searchInput, filters]);

  function toggleStatus(status: (typeof statusOptions)[number][0]): void {
    const statuses = filters.statuses.includes(status) ? filters.statuses.filter((item) => item !== status) : [...filters.statuses, status];
    replaceFilters({ ...filters, statuses, page: 1 });
  }

  function applyTagFilter(): void {
    replaceFilters({ ...filters, tag: tagInput.trim() || null, page: 1 });
  }

  function clearTagFilter(): void {
    setTagInput("");
    replaceFilters({ ...filters, tag: null, page: 1 });
  }

  function selectTask(taskId: string, selected: boolean): void {
    setSelectedTaskIds((current) => {
      const next = new Set(current);
      if (selected) next.add(taskId); else next.delete(taskId);
      return next;
    });
  }

  function inspectTask(taskId: string): void {
    selectTask(taskId, true);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("selected", taskId);
    setSearchParams(nextParams, { replace: true });
  }

  function requestBulkOperation(operation: BulkOperation): void {
    if (selectedTaskIds.size > 0) {
      setBulkTags("");
      setBulkOperation(operation);
    }
  }

  if (taskQuery.isPending) return <section className="ny-workstation-page"><p className="ny-workstation__eyebrow">任务库</p><h1 className="ny-workstation-page__title">任务库</h1><p className="ny-feedback ny-feedback--loading">正在读取任务库。</p></section>;
  if (taskQuery.isError || taskQuery.data === undefined) return <section className="ny-workstation-page"><p className="ny-workstation__eyebrow">任务库</p><h1 className="ny-workstation-page__title">任务库无法读取</h1><button className="ny-button" onClick={() => void taskQuery.refetch()} type="button"><RotateCw aria-hidden="true" size="var(--ny-icon-default)" />重新读取任务库</button></section>;

  const page = taskQuery.data;
  return (
    <section className="ny-task-library" aria-labelledby="task-library-title">
      <header className="ny-task-library__header">
        <div><p className="ny-workstation__eyebrow">任务库</p><h1 className="ny-workstation-page__title" id="task-library-title">任务库</h1></div>
        <div className="ny-task-library__summary" aria-label="任务库摘要">{summaryQuery.data ? summaryItems(summaryQuery.data).map((item) => <span key={item}>{item}</span>) : "正在读取摘要"}</div>
      </header>
      <div className="ny-task-library__filters">
        <label className="ny-task-library__search" htmlFor="task-library-search"><Search aria-hidden="true" size="var(--ny-icon-default)" /><span className="ny-sr-only">搜索任务</span><input className="ny-input" id="task-library-search" onChange={(event) => setSearchInput(event.target.value)} placeholder="搜索标题、来源或任务 ID" role="searchbox" value={searchInput} /></label>
        <fieldset><legend>状态</legend>{statusOptions.map(([status, label]) => <label key={status}><input checked={filters.statuses.includes(status)} onChange={() => toggleStatus(status)} type="checkbox" />{label}</label>)}</fieldset>
        <label>来源<select className="ny-input" onChange={(event) => replaceFilters({ ...filters, sourceKind: sourceKindFromInput(event.target.value), page: 1 })} value={filters.sourceKind}><option value="all">全部</option><option value="bilibili">哔哩哔哩</option><option value="local">本地文件</option></select></label>
        <label>更新开始日期<input className="ny-input" onChange={(event) => replaceFilters({ ...filters, updatedFrom: event.target.value || null, page: 1 })} type="date" value={filters.updatedFrom ?? ""} /></label>
        <label>更新结束日期<input className="ny-input" onChange={(event) => replaceFilters({ ...filters, updatedTo: event.target.value || null, page: 1 })} type="date" value={filters.updatedTo ?? ""} /></label>
        <label>产物状态<select className="ny-input" onChange={(event) => replaceFilters({ ...filters, readiness: readinessFromInput(event.target.value), page: 1 })} value={filters.readiness ?? ""}><option value="">全部</option><option value="ready">可用</option><option value="missing">缺失</option><option value="failed">失败</option><option value="not_ready">未就绪</option></select></label>
        <div className="ny-task-library__tag-filter">
          <label htmlFor="task-library-tag">标签<input className="ny-input" id="task-library-tag" onChange={(event) => setTagInput(event.target.value)} value={tagInput} /></label>
          <div className="ny-task-library__tag-actions">
            <button className="ny-button" onClick={applyTagFilter} type="button">应用标签</button>
            <button className="ny-button ny-button--quiet" disabled={filters.tag === null && tagInput === ""} onClick={clearTagFilter} type="button">清除标签</button>
          </div>
        </div>
        <label>每页<select className="ny-input" onChange={(event) => replaceFilters({ ...filters, page: 1, pageSize: pageSizeFromInput(event.target.value) })} value={filters.pageSize}><option value="25">25</option><option value="50">50</option><option value="100">100</option></select></label>
      </div>
      <div className="ny-task-library__bulk" aria-label="批量任务操作">
        <span>已选择 {selectedTaskIds.size} 项</span>
        <button className="ny-button" disabled={selectedTaskIds.size === 0 || bulkMutation.isPending} onClick={() => requestBulkOperation("archive")} type="button"><Archive aria-hidden="true" size="var(--ny-icon-default)" />归档选中任务</button>
        <button className="ny-button" disabled={selectedTaskIds.size === 0 || bulkMutation.isPending} onClick={() => requestBulkOperation("set_tags")} type="button"><Tags aria-hidden="true" size="var(--ny-icon-default)" />标记选中任务</button>
        <button className="ny-button" disabled={selectedTaskIds.size === 0 || bulkMutation.isPending} onClick={() => requestBulkOperation("requeue")} type="button"><RotateCcw aria-hidden="true" size="var(--ny-icon-default)" />重新排队选中任务</button>
        <button className="ny-button ny-button--danger" disabled={selectedTaskIds.size === 0 || bulkMutation.isPending} onClick={() => requestBulkOperation("delete")} type="button"><Trash2 aria-hidden="true" size="var(--ny-icon-default)" />删除选中任务</button>
      </div>
      {announcement ? <p className="ny-task-library__announcement" role="status">{announcement}</p> : null}
      {page.items.length === 0 ? <div className="ny-feedback ny-feedback--empty"><h2 className="ny-feedback__title">没有匹配任务</h2><p className="ny-feedback__copy">调整筛选条件，或清除搜索词后再试。</p></div> : <TaskTable filters={filters} inspectedTaskId={inspectedTaskId} items={page.items} onInspect={inspectTask} onOpenTask={(taskId) => navigate(`/workstation/tasks/${taskId}`)} onSelectionChange={selectTask} onSort={(sort) => replaceFilters({ ...filters, sort, direction: filters.sort === sort && filters.direction === "desc" ? "asc" : "desc", page: 1 })} selectedTaskIds={selectedTaskIds} />}
      <footer className="ny-task-library__pagination"><span>第 {page.page} / {Math.max(page.page_count, 1)} 页，共 {page.total} 项</span><button aria-label="上一页" className="ny-button" disabled={page.page <= 1} onClick={() => replaceFilters({ ...filters, page: filters.page - 1 })} type="button"><ChevronLeft aria-hidden="true" size="var(--ny-icon-default)" />上一页</button><button aria-label="下一页" className="ny-button" disabled={page.page >= page.page_count} onClick={() => replaceFilters({ ...filters, page: filters.page + 1 })} type="button">下一页<ChevronRight aria-hidden="true" size="var(--ny-icon-default)" /></button></footer>
      <Dialog.Root onOpenChange={(open) => { if (!open) setBulkOperation(null); }} open={bulkOperation !== null}>{bulkOperation ? <Dialog.Portal><Dialog.Overlay className="ny-dialog-overlay" /><Dialog.Content className="ny-overlay ny-dialog"><Dialog.Title className="ny-overlay__title">{bulkOperationCopy(bulkOperation).title}</Dialog.Title><Dialog.Description className="ny-overlay__description">{bulkOperationCopy(bulkOperation).description}</Dialog.Description>{bulkOperation === "set_tags" ? <label className="ny-field" htmlFor="task-library-bulk-tags">批量标签<input className="ny-input" id="task-library-bulk-tags" onChange={(event) => setBulkTags(event.target.value)} placeholder="用中文逗号分隔" value={bulkTags} /></label> : null}<div className="ny-overlay__actions"><Dialog.Close className="ny-button" type="button">取消</Dialog.Close><button className={bulkOperation === "delete" ? "ny-button ny-button--danger" : "ny-button ny-button--primary"} onClick={() => { const tags = bulkOperation === "set_tags" ? parseBulkTags(bulkTags) : undefined; bulkMutation.mutate({ operation: bulkOperation, tags }); setBulkOperation(null); }} type="button">{bulkOperationCopy(bulkOperation).confirmLabel}</button></div></Dialog.Content></Dialog.Portal> : null}</Dialog.Root>
    </section>
  );
}
