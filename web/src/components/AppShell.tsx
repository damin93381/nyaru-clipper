import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { getRuntimeCapabilities } from "../lib/api";
import { APP_SHELL_COPY } from "../lib/copy/appShell";
import { EnvironmentStatusCard } from "./EnvironmentStatusCard";

export function AppShell() {
  const { header, navigation, sideRail, futureWorkspace } = APP_SHELL_COPY;
  const runtimeCapabilitiesQuery = useQuery({
    queryKey: ["runtime-capabilities"],
    queryFn: getRuntimeCapabilities,
    staleTime: 60_000,
  });

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <div>
          <p className="eyebrow">{header.eyebrow}</p>
          <h1>{header.title}</h1>
          <p className="header-copy">{header.description}</p>
        </div>

        <nav aria-label={navigation.primaryAriaLabel} className="app-shell__nav">
          <NavLink className="nav-link" to="/">
            {navigation.newTask}
          </NavLink>
        </nav>
      </header>

      <div className="app-shell__body">
        <aside className="app-shell__rail" aria-label={sideRail.ariaLabel}>
          <EnvironmentStatusCard
            capabilities={runtimeCapabilitiesQuery.data}
            errorMessage={runtimeCapabilitiesQuery.error instanceof Error ? runtimeCapabilitiesQuery.error.message : null}
            isLoading={runtimeCapabilitiesQuery.isLoading}
          />

          <section className="panel reserved-panel" aria-label={sideRail.futureTaskList.title}>
            <p className="eyebrow">{sideRail.futureTaskList.eyebrow}</p>
            <h2>{sideRail.futureTaskList.title}</h2>
            <p>{sideRail.futureTaskList.description}</p>
            <ul className="placeholder-list">
              <li>{sideRail.futureTaskList.items[0]}</li>
              <li>{sideRail.futureTaskList.items[1]}</li>
              <li>{sideRail.futureTaskList.items[2]}</li>
            </ul>
          </section>
        </aside>

        <main className="app-shell__main">
          <Outlet />
        </main>

        <aside className="panel reserved-panel" aria-label={futureWorkspace.ariaLabel}>
          <p className="eyebrow">{futureWorkspace.eyebrow}</p>
          <h2>{futureWorkspace.title}</h2>
          <p>{futureWorkspace.description}</p>
          <ul className="placeholder-list">
            <li>{futureWorkspace.items[0]}</li>
            <li>{futureWorkspace.items[1]}</li>
            <li>{futureWorkspace.items[2]}</li>
          </ul>
        </aside>
      </div>
    </div>
  );
}
