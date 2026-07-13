import { Outlet } from "react-router-dom";
import type { ReactNode } from "react";

import type { WorkstationConnectionState } from "../api/useWorkstationEvents";
import "../design/tokens.css";
import "../design/global.css";
import "../design/primitives.css";
import "../design/workstation-shell.css";
import { ConnectionBanner } from "./ConnectionBanner";
import { ContextInspector } from "./ContextInspector";
import { Sidebar } from "./Sidebar";

interface WorkstationShellProps {
  readonly connectionState: WorkstationConnectionState;
}

export function AppShell({ connectionState }: WorkstationShellProps): ReactNode {
  return (
    <div className="ny-workstation">
      <ConnectionBanner state={connectionState} />
      <div className="ny-workstation__grid">
        <Sidebar />
        <main className="ny-workstation__main" tabIndex={-1}>
          <Outlet />
        </main>
        <ContextInspector />
      </div>
    </div>
  );
}
