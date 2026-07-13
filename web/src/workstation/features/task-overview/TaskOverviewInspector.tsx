import type { ReactNode } from "react";

import { ArtifactList } from "./ArtifactList";
import type { WorkstationTaskOverview } from "./api";

interface TaskOverviewInspectorProps {
  readonly selectedStage: string | null;
  readonly task: WorkstationTaskOverview;
}

export function TaskOverviewInspector({ selectedStage, task }: TaskOverviewInspectorProps): ReactNode {
  const safeLogs = selectedStage === null ? task.safe_logs : task.safe_logs.filter((log) => log.stage_name === selectedStage);
  return (
    <div className="ny-overview-inspector">
      <section className="ny-overview-inspector__section" aria-labelledby="task-safe-log-title">
        <p className="ny-workstation__eyebrow">安全日志</p>
        <h2 className="ny-workstation__inspector-heading" id="task-safe-log-title">{selectedStage ? "当前阶段摘要" : "任务运行摘要"}</h2>
        {safeLogs.length === 0 ? <p className="ny-workstation-page__copy">当前阶段尚无可公开的日志摘要。</p> : <ul className="ny-overview-inspector__list">{safeLogs.map((log) => <li key={log.stage_name}><strong>{log.display_label}</strong><span>{log.summary ?? "暂无安全日志摘要。"}</span></li>)}</ul>}
      </section>
      <ArtifactList artifacts={task.artifacts} selectedStage={selectedStage} />
    </div>
  );
}
