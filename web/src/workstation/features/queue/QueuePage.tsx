import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { QueueConflictError, getQueue, reorderQueue, reorderSnapshot, setQueueItemState } from "./api";
import { QueueInspector } from "./QueueInspector";
import { QueueList } from "./QueueList";
import { workstationKeys } from "../../api/queryKeys";
import type { QueueSnapshot, QueueState } from "./api";

interface ReorderVariables {
  readonly expectedRevision: number;
  readonly orderedTaskIds: readonly string[];
}

interface ReorderContext {
  readonly previous: QueueSnapshot | undefined;
}

export function QueuePage(): ReactNode {
  const queryClient = useQueryClient();
  const [announcement, setAnnouncement] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const queueQuery = useQuery({ queryKey: workstationKeys.queue, queryFn: getQueue });
  const reorderMutation = useMutation<QueueSnapshot, Error, ReorderVariables, ReorderContext>({
    mutationFn: ({ expectedRevision, orderedTaskIds }) => reorderQueue(orderedTaskIds, expectedRevision),
    onMutate: ({ orderedTaskIds }) => {
      const previous = queryClient.getQueryData<QueueSnapshot>(workstationKeys.queue);
      if (previous !== undefined) queryClient.setQueryData(workstationKeys.queue, reorderSnapshot(previous, orderedTaskIds));
      return { previous };
    },
    onSuccess: (snapshot) => queryClient.setQueryData(workstationKeys.queue, snapshot),
    onError: (error, _variables, context) => {
      if (error instanceof QueueConflictError) {
        queryClient.setQueryData(workstationKeys.queue, error.snapshot);
        setAnnouncement("队列已在其他操作中变化，已恢复最新顺序。");
        return;
      }
      if (context?.previous !== undefined) queryClient.setQueryData(workstationKeys.queue, context.previous);
      setAnnouncement("队列排序没有保存，请重试。");
    },
  });
  const stateMutation = useMutation({
    mutationFn: ({ state, taskId }: { readonly state: QueueState; readonly taskId: string }) => setQueueItemState(taskId, state),
    onSuccess: (snapshot) => queryClient.setQueryData(workstationKeys.queue, snapshot),
    onError: () => setAnnouncement("队列状态没有保存，请重试。"),
  });

  function reorder(orderedTaskIds: readonly string[]): void {
    const snapshot = queryClient.getQueryData<QueueSnapshot>(workstationKeys.queue);
    if (snapshot !== undefined) reorderMutation.mutate({ expectedRevision: snapshot.revision, orderedTaskIds });
  }

  function setState(taskId: string, state: QueueState): void {
    stateMutation.mutate({ state, taskId });
  }

  if (queueQuery.isPending) return <section className="ny-workstation-page"><p className="ny-workstation__eyebrow">处理队列</p><h1 className="ny-workstation-page__title">处理队列</h1><p className="ny-feedback ny-feedback--loading">正在读取处理队列。</p></section>;
  if (queueQuery.isError || queueQuery.data === undefined) return <section className="ny-workstation-page"><p className="ny-workstation__eyebrow">处理队列</p><h1 className="ny-workstation-page__title">处理队列无法读取</h1><button className="ny-button" onClick={() => void queueQuery.refetch()} type="button"><RotateCw aria-hidden="true" size="var(--ny-icon-default)" />重新读取处理队列</button></section>;

  const snapshot = queueQuery.data;
  return (
    <section className="ny-task-library" aria-labelledby="queue-page-title">
      <header className="ny-task-library__header"><div><p className="ny-workstation__eyebrow">处理队列</p><h1 className="ny-workstation-page__title" id="queue-page-title">处理队列</h1></div><span className="ny-task-library__summary">队列版本 {snapshot.revision}</span></header>
      {announcement ? <p className="ny-task-library__announcement" role="status">{announcement}</p> : null}
      <QueueList isMutating={reorderMutation.isPending || stateMutation.isPending} onReorder={reorder} onSelect={setSelectedTaskId} onSetState={setState} selectedTaskId={selectedTaskId} snapshot={snapshot} />
      <QueueInspector selectedTaskId={selectedTaskId} snapshot={snapshot} />
    </section>
  );
}
