import { Outlet } from "react-router-dom";
import { Plus } from "lucide-react";
import { useRef, useState } from "react";
import type { ReactNode } from "react";

import type { WorkstationConnectionState } from "../api/useWorkstationEvents";
import "../design/tokens.css";
import "../design/global.css";
import "../design/primitives.css";
import "../design/workstation-shell.css";
import { ConnectionBanner } from "./ConnectionBanner";
import { ContextInspector } from "./ContextInspector";
import { Sidebar } from "./Sidebar";
import { NewTaskDrawer } from "../features/task-create/NewTaskDrawer";

interface WorkstationShellProps {
  readonly connectionState: WorkstationConnectionState;
}

export function AppShell({ connectionState }: WorkstationShellProps): ReactNode {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerTriggerRef = useRef<HTMLButtonElement>(null);

  function handleDrawerOpenChange(open: boolean): void {
    setDrawerOpen(open);
    if (!open) requestAnimationFrame(() => drawerTriggerRef.current?.focus());
  }

  return (
    <div className="ny-workstation">
      <ConnectionBanner state={connectionState} />
      <div className="ny-workstation__grid">
        <Sidebar />
        <main className="ny-workstation__main" tabIndex={-1}>
          <div className="ny-workstation__command-bar"><button className="ny-button ny-button--primary" onClick={() => setDrawerOpen(true)} ref={drawerTriggerRef} type="button"><Plus aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />新建任务</button></div>
          <Outlet />
        </main>
        <ContextInspector />
      </div>
      <NewTaskDrawer onOpenChange={handleDrawerOpenChange} open={drawerOpen} />
    </div>
  );
}
