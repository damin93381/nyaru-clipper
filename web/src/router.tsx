import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import type { ReactNode } from "react";

import { WorkstationApp } from "./workstation/WorkstationApp";

function LegacyTaskRedirect(): ReactNode {
  const { taskId } = useParams();
  return <Navigate replace to={taskId === undefined ? "/workstation" : `/workstation/tasks/${taskId}`} />;
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<WorkstationApp />} />
        <Route path="/workstation/*" element={<WorkstationApp />} />
        <Route path="/tasks/:taskId" element={<LegacyTaskRedirect />} />
      </Routes>
    </BrowserRouter>
  );
}
