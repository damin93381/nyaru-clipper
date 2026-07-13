import type { ReactNode } from "react";

import { useWorkstationEvents } from "./api/useWorkstationEvents";
import { WorkstationRouter } from "./routes/WorkstationRouter";

export function WorkstationApp(): ReactNode {
  const connection = useWorkstationEvents();

  return <WorkstationRouter connectionState={connection.state} />;
}
