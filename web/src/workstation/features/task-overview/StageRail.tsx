import { Check, CircleDashed, CircleX, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import { getExecutionProgressLabel } from "../../../lib/copy/glossary";
import { CANONICAL_STAGES, formatStageLabel } from "../../../lib/types";
import type { WorkstationTaskOverview } from "./api";

interface StageRailProps {
  readonly executionProgress: WorkstationTaskOverview["execution_progress"];
  readonly onSelectStage: (stageName: string) => void;
  readonly selectedStage: string | null;
  readonly stages: WorkstationTaskOverview["stages"];
}

type StageTone = "complete" | "failed" | "pending" | "running" | "warning";

function stageTone(status: string): StageTone {
  switch (status) {
    case "success": return "complete";
    case "failed": return "failed";
    case "cancelled": return "warning";
    case "running": return "running";
    default: return "pending";
  }
}

function StageIcon({ tone }: { readonly tone: StageTone }): ReactNode {
  switch (tone) {
    case "complete": return <Check aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
    case "failed": return <CircleX aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
    case "running": return <LoaderCircle aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
    case "warning": return <CircleDashed aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
    case "pending": return <CircleDashed aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
  }
}

export function StageRail({ executionProgress, onSelectStage, selectedStage, stages }: StageRailProps): ReactNode {
  const stagesByName = new Map(stages.map((stage) => [stage.name, stage]));
  const selectedStageSummary = selectedStage === null
    ? null
    : stagesByName.get(selectedStage)?.summary ?? null;
  const progressLabel = executionProgress === null
    ? null
    : getExecutionProgressLabel({
      phase: executionProgress.current_phase,
      phaseCount: executionProgress.phase_count,
      phaseIndex: executionProgress.phase_index,
      stageName: executionProgress.stage_name,
    });
  const stageMessage = executionProgress?.latest_message ?? selectedStageSummary;

  return (
    <section className="ny-overview__stage-panel" aria-labelledby="task-stage-rail-title">
      <div className="ny-overview__section-heading">
        <div>
          <p className="ny-workstation__eyebrow">标准流水线</p>
          <h2 className="ny-showcase__section-heading" id="task-stage-rail-title">处理进度</h2>
        </div>
        {progressLabel ? <p className="ny-overview__progress-label">{progressLabel}</p> : null}
      </div>
      <ol aria-label="任务阶段" className="ny-progress">
        {CANONICAL_STAGES.map((stageName) => {
          const stage = stagesByName.get(stageName);
          const tone = stageTone(stage?.status ?? "pending");
          return (
            <li className={`ny-progress__stage ny-progress__stage--${tone}`} key={stageName}>
              <button aria-pressed={selectedStage === stageName} className="ny-progress__stage-button" onClick={() => onSelectStage(stageName)} type="button">
                <StageIcon tone={tone} />
                <span className="ny-progress__stage-label">{formatStageLabel(stageName)}</span>
                <span className="ny-sr-only">：{stage?.status ?? "pending"}</span>
              </button>
            </li>
          );
        })}
      </ol>
      {stageMessage ? <p className="ny-overview__stage-message" role="status">{stageMessage}</p> : null}
    </section>
  );
}
