import { CircleDotDashed, ListChecks } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import type { ReactNode } from "react";

import { getTaskLibraryPage, getTaskLibrarySummary } from "../features/task-library/api";
import { workstationKeys } from "../api/queryKeys";
import { TaskInspector } from "../features/task-library/TaskInspector";

const runningTaskFilters = {
  direction: "desc",
  page: 1,
  pageSize: 25,
  query: "",
  readiness: null,
  sort: "updated_at",
  sourceKind: "all",
  statuses: ["running"],
  tag: null,
  updatedFrom: null,
  updatedTo: null,
} as const;

function stageLabel(stage: string | null): string {
  switch (stage) {
    case "ingest": return "采集";
    case "media_prep": return "媒体准备";
    case "asr": return "转写";
    case "translation": return "翻译";
    case "highlight": return "高光筛选";
    case "export": return "导出";
    case "report": return "报告";
    case null: return "等待分配";
    default: return stage;
  }
}

export function ContextInspector(): ReactNode {
  const { taskId } = useParams();
  const [searchParams] = useSearchParams();
  const selectedTaskId = searchParams.get("selected");
  const showWorkspaceSummary = selectedTaskId === null && taskId === undefined;
  const summaryQuery = useQuery({ queryKey: workstationKeys.summary, queryFn: getTaskLibrarySummary, enabled: showWorkspaceSummary });
  const activeTaskQuery = useQuery({
    queryKey: workstationKeys.list({ direction: "desc", page: 1, page_size: 25, sort: "updated_at", statuses: ["running"] }),
    queryFn: () => getTaskLibraryPage(runningTaskFilters),
    enabled: showWorkspaceSummary,
  });

  if (selectedTaskId) {
    return <aside className="ny-workstation__inspector" aria-label="上下文检查器"><TaskInspector taskId={selectedTaskId} /></aside>;
  }

  return (
    <aside className="ny-workstation__inspector" aria-label="上下文检查器">
      <p className="ny-workstation__eyebrow">上下文</p>
      <h2 className="ny-workstation__inspector-heading">{taskId ? "已选择任务" : "工作台状态"}</h2>
      <div className="ny-workstation__inspector-state">
        {taskId ? <ListChecks aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" /> : <CircleDotDashed aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />}
        <p lang="zh-CN">
          {taskId ? <><span className="ny-workstation__inspector-task-reference">任务 {taskId}</span>的详细进度和恢复操作将<span className="ny-workstation__inspector-copy-phrase">在<span className="ny-workstation__inspector-copy-phrase">此处显示</span></span>。</> : <>
            从任务库选择一项，<span className="ny-workstation__inspector-copy-phrase">即可在不离开<span className="ny-workstation__inspector-copy-phrase">当前工作区</span><span className="ny-workstation__inspector-copy-phrase">的情况下</span></span>查看状态。
          </>}
        </p>
      </div>
      {summaryQuery.data?.active && activeTaskQuery.data?.items[0] ? <section className="ny-workstation__inspector-state" aria-labelledby="active-gpu-job-title"><p className="ny-workstation__eyebrow">执行中</p><h3 className="ny-workstation__inspector-heading" id="active-gpu-job-title">GPU 作业</h3><p className="ny-workstation__inspector-task-reference"><span className="ny-workstation__inspector-task-title" title={activeTaskQuery.data.items[0].title}>{activeTaskQuery.data.items[0].title}</span></p><p>{stageLabel(activeTaskQuery.data.items[0].current_stage)} · {activeTaskQuery.data.items[0].progress_percent}%</p></section> : null}
    </aside>
  );
}
