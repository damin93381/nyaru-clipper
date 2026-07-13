import type { ReactNode } from "react";

import type { QueueItem, QueueSnapshot } from "./api";

interface QueueInspectorProps {
  readonly selectedTaskId: string | null;
  readonly snapshot: QueueSnapshot;
}

function selectedItem(snapshot: QueueSnapshot, taskId: string | null): QueueItem | undefined {
  if (taskId === null) return undefined;
  const items = snapshot.active === null ? [...snapshot.queued, ...snapshot.paused] : [snapshot.active, ...snapshot.queued, ...snapshot.paused];
  return items.find((item) => item.task_id === taskId);
}

function stateLabel(state: string): string {
  switch (state) {
    case "running": return "正在执行";
    case "queued": return "等待处理";
    case "paused": return "已暂停";
    default: return state;
  }
}

export function QueueInspector({ selectedTaskId, snapshot }: QueueInspectorProps): ReactNode {
  const item = selectedItem(snapshot, selectedTaskId);

  return (
    <section className="ny-showcase__section" aria-labelledby="queue-inspector-title">
      <p className="ny-workstation__eyebrow">队列检查器</p>
      <h2 className="ny-showcase__section-heading" id="queue-inspector-title">{item ? "已选队列项" : "选择队列项"}</h2>
      {item ? <dl className="ny-task-library__summary"><div><dt>任务</dt><dd className="ny-table__technical">{item.task_id}</dd></div><div><dt>状态</dt><dd>{stateLabel(item.state)}</dd></div><div><dt>位置</dt><dd>{item.state === "queued" ? item.position : "—"}</dd></div><div><dt>优先级</dt><dd>{item.priority}</dd></div></dl> : <p className="ny-workstation-page__copy">选择一项以查看当前队列位置与状态。</p>}
    </section>
  );
}
