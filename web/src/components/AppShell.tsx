import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { getRuntimeCapabilities } from "../lib/api";
import { EnvironmentStatusCard } from "./EnvironmentStatusCard";

export function AppShell() {
  const runtimeCapabilitiesQuery = useQuery({
    queryKey: ["runtime-capabilities"],
    queryFn: getRuntimeCapabilities,
    staleTime: 60_000,
  });

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <div>
          <p className="eyebrow">Single-host workstation MVP</p>
          <h1>Bilibili VTuber Suite</h1>
          <p className="header-copy">Operational shell for submission, stage tracking, and later review workflows.</p>
        </div>

        <nav aria-label="Primary" className="app-shell__nav">
          <NavLink className="nav-link" to="/">
            New task
          </NavLink>
        </nav>
      </header>

      <div className="app-shell__body">
        <aside className="app-shell__rail" aria-label="Environment and future task list region">
          <EnvironmentStatusCard
            capabilities={runtimeCapabilitiesQuery.data}
            errorMessage={runtimeCapabilitiesQuery.error instanceof Error ? runtimeCapabilitiesQuery.error.message : null}
            isLoading={runtimeCapabilitiesQuery.isLoading}
          />

          <section className="panel reserved-panel" aria-label="Future task list region">
            <p className="eyebrow">Reserved region</p>
            <h2>Future task list</h2>
            <p>Leave room here for history, queue visibility, and later batch/subscription views.</p>
            <ul className="placeholder-list">
              <li>Active queue snapshot</li>
              <li>Recent task history</li>
              <li>Task filters and search</li>
            </ul>
          </section>
        </aside>

        <main className="app-shell__main">
          <Outlet />
        </main>

        <aside className="panel reserved-panel" aria-label="Future workspace region">
          <p className="eyebrow">Reserved region</p>
          <h2>Future workspace</h2>
          <p>Subtitle review, candidate confirmation, and exports will expand into this column in Task 10.</p>
          <ul className="placeholder-list">
            <li>Bilingual subtitle review</li>
            <li>Highlight candidate controls</li>
            <li>Artifact download shortcuts</li>
          </ul>
        </aside>
      </div>
    </div>
  );
}
