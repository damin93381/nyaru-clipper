import { Archive, Save, Tags } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { components } from "../../../generated/api-schema";

import { getTaskOverview, updateTaskMetadata } from "./api";
import { workstationKeys } from "../../api/queryKeys";

interface TaskInspectorProps {
  readonly taskId: string;
}

function formatStorage(bytes: number): string {
  return `${(bytes / 1_024).toFixed(bytes >= 1_024 ? 1 : 0)} KB`;
}

function parseTags(value: string): string[] {
  return value.split("，").map((tag) => tag.trim()).filter(Boolean);
}

function hasSameTags(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((tag, index) => tag === right[index]);
}

export function TaskInspector({ taskId }: TaskInspectorProps): ReactNode {
  const queryClient = useQueryClient();
  const taskQuery = useQuery({ queryKey: workstationKeys.detail(taskId), queryFn: () => getTaskOverview(taskId) });
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const saveMetadata = useMutation({
    mutationFn: (metadata: components["schemas"]["TaskPatchRequest"]) => updateTaskMetadata(taskId, metadata),
    onSuccess: (task) => {
      queryClient.setQueryData(workstationKeys.detail(taskId), task);
      void queryClient.invalidateQueries({ queryKey: ["workstation", "tasks"] });
    },
  });
  const archiveTask = useMutation({
    mutationFn: (archived: boolean) => updateTaskMetadata(taskId, { archived }),
    onSuccess: (task) => {
      queryClient.setQueryData(workstationKeys.detail(taskId), task);
      void queryClient.invalidateQueries({ queryKey: ["workstation", "tasks"] });
    },
  });

  useEffect(() => {
    if (taskQuery.data) {
      setTitle(taskQuery.data.title);
      setTags(taskQuery.data.tags.join("，"));
    }
  }, [taskQuery.data]);

  if (taskQuery.isPending) return <p className="ny-workstation__inspector-state">正在读取任务上下文。</p>;
  if (taskQuery.isError || taskQuery.data === undefined) return <p className="ny-workstation__inspector-state">任务上下文暂时不可用。</p>;

  const task = taskQuery.data;
  const archived = task.archived_at !== null;
  function saveChangedMetadata(): void {
    const metadata: components["schemas"]["TaskPatchRequest"] = {};
    const nextTitle = title.trim();
    const nextTags = parseTags(tags);
    if (nextTitle !== task.title) metadata.title = nextTitle;
    if (!hasSameTags(nextTags, task.tags)) metadata.tags = nextTags;
    if (metadata.title !== undefined || metadata.tags !== undefined) saveMetadata.mutate(metadata);
  }

  return (
    <div className="ny-task-inspector">
      <p className="ny-workstation__eyebrow">已选择任务</p>
      <h2 className="ny-workstation__inspector-heading ny-task-inspector__heading" title={task.title}>{task.title}</h2>
      <dl className="ny-task-inspector__facts">
        <div><dt>状态</dt><dd>{task.status}</dd></div>
        <div><dt>阶段</dt><dd>{task.current_stage ?? "等待分配"}</dd></div>
        <div><dt>存储</dt><dd>{formatStorage(task.storage_bytes)}</dd></div>
      </dl>
      <label className="ny-field" htmlFor="task-inspector-title">任务标题
        <input className="ny-input" id="task-inspector-title" onChange={(event) => setTitle(event.target.value)} value={title} />
      </label>
      <label className="ny-field" htmlFor="task-inspector-tags">标签（用中文逗号分隔）
        <input className="ny-input" id="task-inspector-tags" onChange={(event) => setTags(event.target.value)} value={tags} />
      </label>
      <button className="ny-button ny-button--primary" disabled={saveMetadata.isPending} onClick={saveChangedMetadata} type="button">
        <Save aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />保存元数据
      </button>
      <button className="ny-button" disabled={archiveTask.isPending} onClick={() => archiveTask.mutate(!archived)} type="button">
        <Archive aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{archived ? "取消归档" : "归档任务"}
      </button>
      {saveMetadata.isError || archiveTask.isError ? <p className="ny-field__message ny-field__message--error" role="alert">更新没有保存，请重试。</p> : null}
      {saveMetadata.isSuccess ? <p className="ny-field__message"><Tags aria-hidden="true" size="var(--ny-icon-default)" />已保存任务元数据。</p> : null}
    </div>
  );
}
