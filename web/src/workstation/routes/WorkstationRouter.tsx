import { Route, Routes, useParams } from "react-router-dom";
import type { ReactNode } from "react";

import type { WorkstationConnectionState } from "../api/useWorkstationEvents";
import { AppShell } from "../components/AppShell";
import { PrimitiveShowcasePage } from "./PrimitiveShowcasePage";
import { TaskLibraryPage } from "../features/task-library/TaskLibraryPage";

interface WorkstationRouterProps {
  readonly connectionState: WorkstationConnectionState;
}

function WorkspacePage({ title, description }: { readonly title: string; readonly description: string }): ReactNode {
  return (
    <section className="ny-workstation-page" aria-labelledby="workstation-page-title">
      <p className="ny-workstation__eyebrow">工作区</p>
      <h1 className="ny-workstation-page__title" id="workstation-page-title">{title}</h1>
      <p className="ny-workstation-page__copy">{description}</p>
    </section>
  );
}

function TaskWorkspacePage(): ReactNode {
  const { taskId } = useParams();

  return <WorkspacePage description={`正在准备任务 ${taskId ?? ""} 的工作区快照。`} title="任务概览" />;
}

export function WorkstationRouter({ connectionState }: WorkstationRouterProps): ReactNode {
  return (
    <Routes>
      <Route path="*" element={<AppShell connectionState={connectionState} />}>
        <Route index element={<TaskLibraryPage />} />
        <Route path="queue" element={<WorkspacePage description="处理队列会在下一步提供排序、暂停与恢复控制。" title="处理队列" />} />
        <Route path="tasks/:taskId" element={<TaskWorkspacePage />} />
        {import.meta.env.DEV ? <Route path="design-system" element={<PrimitiveShowcasePage />} /> : null}
      </Route>
    </Routes>
  );
}
