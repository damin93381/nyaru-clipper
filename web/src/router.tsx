import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { NewTaskPage } from "./pages/NewTaskPage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { WorkstationApp } from "./workstation/WorkstationApp";

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/workstation/*" element={<WorkstationApp />} />
        <Route element={<AppShell />}>
          <Route path="/" element={<NewTaskPage />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
