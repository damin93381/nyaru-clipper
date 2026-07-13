import { flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { ArrowDown, ArrowLeftRight, ArrowUp, ChevronsUpDown, ExternalLink } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import type { ReactNode } from "react";

import type { TaskListItem } from "./api";
import type { TaskLibraryFilters } from "./filters";
import { getStageLabel } from "../../../lib/copy/glossary";

interface TaskTableProps {
  readonly filters: TaskLibraryFilters;
  readonly items: readonly TaskListItem[];
  readonly selectedTaskIds: ReadonlySet<string>;
  readonly inspectedTaskId: string | null;
  readonly onSelectionChange: (taskId: string, selected: boolean) => void;
  readonly onInspect: (taskId: string) => void;
  readonly onOpenTask: (taskId: string) => void;
  readonly onSort: (sort: TaskLibraryFilters["sort"]) => void;
}

function taskStatusLabel(status: TaskListItem["status"]): string {
  const labels: Record<TaskListItem["status"], string> = {
    pending: "待处理",
    running: "运行中",
    success: "已完成",
    failed: "已失败",
    cancelled: "已取消",
  };
  return labels[status];
}

function taskStatusClass(status: TaskListItem["status"]): string {
  if (status === "failed") return "ny-stamp--failed";
  if (status === "success") return "ny-stamp--success";
  if (status === "running") return "ny-stamp--running";
  return "ny-stamp--warning";
}

function formatStorage(bytes: number): string {
  return `${(bytes / 1_024).toFixed(bytes >= 1_024 ? 1 : 0)} KB`;
}

function formatUpdatedAt(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function stickyColumnClass(columnId: string): string | undefined {
  if (columnId === "selection") return "ny-task-table__sticky ny-task-table__sticky--selection";
  if (columnId === "title") return "ny-task-table__sticky ny-task-table__sticky--title";
  return undefined;
}

export function TaskTable(props: TaskTableProps): ReactNode {
  const columns: ColumnDef<TaskListItem>[] = [
    {
      id: "selection",
      header: "选择",
      cell: ({ row }) => {
        const checked = props.selectedTaskIds.has(row.original.task_id);
        return (
          <label
            className="ny-task-table__selection-target"
            data-testid={`task-selection-target-${row.original.task_id}`}
            onClick={(event) => event.stopPropagation()}
          >
            <input
              aria-label={`选择任务 ${row.original.title}`}
              checked={checked}
              className="ny-task-table__selection-control"
              onChange={() => props.onSelectionChange(row.original.task_id, !checked)}
              type="checkbox"
            />
          </label>
        );
      },
    },
    {
      accessorKey: "title",
      header: "任务",
      cell: ({ row }) => (
        <span className="ny-task-table__title" title={row.original.title}>{row.original.title}</span>
      ),
    },
    {
      accessorKey: "status",
      header: "状态",
      cell: ({ row }) => <span className={`ny-stamp ${taskStatusClass(row.original.status)}`}>{taskStatusLabel(row.original.status)}</span>,
    },
    {
      accessorKey: "tags",
      header: "标签",
      cell: ({ row }) => row.original.tags.length > 0 ? (
        <span className="ny-task-table__tags" title={row.original.tags.join("，")}>
          {row.original.tags.map((tag) => <span className="ny-task-table__tag" key={tag}>{tag}</span>)}
        </span>
      ) : <span className="ny-task-table__tags ny-task-table__tags--empty">无标签</span>,
    },
    {
      accessorKey: "source_label",
      header: "来源",
      cell: ({ row }) => <span>{row.original.source_label}</span>,
    },
    {
      accessorKey: "current_stage",
      header: "当前阶段",
      cell: ({ row }) => <span className="ny-task-table__stage" title={row.original.current_stage ?? "等待分配"}>{row.original.current_stage ? getStageLabel(row.original.current_stage) : "等待分配"}</span>,
    },
    {
      accessorKey: "progress_percent",
      header: "进度",
      cell: ({ row }) => <data className="ny-table__technical" value={row.original.progress_percent}>{row.original.progress_percent}%</data>,
    },
    {
      accessorKey: "updated_at",
      header: "更新",
      cell: ({ row }) => <time dateTime={row.original.updated_at}>{formatUpdatedAt(row.original.updated_at)}</time>,
    },
    {
      accessorKey: "storage_bytes",
      header: "存储",
      cell: ({ row }) => <span className="ny-table__technical">{formatStorage(row.original.storage_bytes)}</span>,
    },
  ];
  const table = useReactTable({
    data: [...props.items],
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
  });

  function sortIcon(sort: TaskLibraryFilters["sort"]): ReactNode {
    if (props.filters.sort !== sort) return <ChevronsUpDown aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
    return props.filters.direction === "asc"
      ? <ArrowUp aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />
      : <ArrowDown aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
  }

  function isSortableColumn(columnId: string): columnId is TaskLibraryFilters["sort"] {
    return columnId === "title" || columnId === "updated_at" || columnId === "storage_bytes";
  }

  return (
    <div
      aria-describedby="task-table-scroll-instructions"
      aria-label="任务表格，可水平滚动"
      className="ny-task-table__scroll"
      onKeyDown={(event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        event.currentTarget.scrollBy({ behavior: "smooth", left: event.key === "ArrowRight" ? event.currentTarget.clientWidth : -event.currentTarget.clientWidth });
      }}
      role="region"
      tabIndex={0}
    >
      <table className="ny-table ny-task-table">
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const sort = header.column.id;
                const ariaSort = isSortableColumn(sort) && props.filters.sort === sort
                  ? (props.filters.direction === "asc" ? "ascending" : "descending")
                  : undefined;
                return <th aria-sort={ariaSort} className={stickyColumnClass(sort)} key={header.id} scope="col">
                  {isSortableColumn(sort) ? (
                    <button className="ny-task-table__sort" onClick={() => props.onSort(sort)} type="button">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {sortIcon(sort)}
                    </button>
                  ) : flexRender(header.column.columnDef.header, header.getContext())}
                </th>;
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => {
            const selected = props.selectedTaskIds.has(row.original.task_id);
            const inspected = props.inspectedTaskId === row.original.task_id;
            return (
              <tr
                aria-selected={selected || inspected}
                className={row.original.status === "failed" ? "ny-table__row--failed" : undefined}
                key={row.id}
                onClick={() => props.onInspect(row.original.task_id)}
                onDoubleClick={() => props.onOpenTask(row.original.task_id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") props.onOpenTask(row.original.task_id);
                }}
                tabIndex={0}
              >
                {row.getVisibleCells().map((cell) => <td className={stickyColumnClass(cell.column.id)} key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="ny-task-table__scroll-instructions" id="task-table-scroll-instructions"><ArrowLeftRight aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />进度、更新时间和存储位于右侧；可横向滚动查看。聚焦表格后，可使用左右方向键滚动。</p>
      <p className="ny-task-table__hint"><ExternalLink aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />按 Enter 或双击打开任务概览。</p>
    </div>
  );
}
