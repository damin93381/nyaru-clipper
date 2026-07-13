import { Radio, RefreshCw, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import type { WorkstationConnectionState } from "../api/useWorkstationEvents";

interface ConnectionBannerProps {
  readonly state: WorkstationConnectionState;
}

export function ConnectionBanner({ state }: ConnectionBannerProps): ReactNode {
  if (state === "open") {
    return (
      <p className="ny-connection ny-connection--open" role="status">
        <Radio aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />
        实时连接已恢复
      </p>
    );
  }

  if (state === "fallback") {
    return (
      <p className="ny-connection ny-connection--fallback" role="status">
        <TriangleAlert aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />
        实时连接不可用，正在每 15 秒刷新工作台快照。
      </p>
    );
  }

  return (
    <p className="ny-connection ny-connection--connecting" role="status">
      <RefreshCw aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />
      正在建立实时连接。
    </p>
  );
}
