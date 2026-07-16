import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWorkstation } from "../../../testing/renderWorkstation";
import { StageRail } from "../StageRail";
import type { WorkstationTaskOverview } from "../api";

const stages = [
  { attempts: 1, failure_code: null, finished_at: null, name: "ingest", planned: false, started_at: null, status: "running", summary: null },
] satisfies WorkstationTaskOverview["stages"];

describe("StageRail", () => {
  it.each([
    ["asr", "chunk", 2, 5, "ASR 2/5"],
    ["translation", "chunk", 4, 5, "Translation 4/5"],
    ["translation", "merge", 5, 5, "Translation merge"],
    ["translation", "proofread", 5, 5, "Translation proofread"],
  ] as const)("renders the safe %s %s substep", (stageName, currentPhase, phaseIndex, phaseCount, expectedLabel) => {
    renderWorkstation(
      <StageRail
        executionProgress={{ current_phase: currentPhase, heartbeat_at: null, latest_message: expectedLabel, phase_count: phaseCount, phase_index: phaseIndex, phase_started_at: null, phases: [], stage_name: stageName }}
        onSelectStage={vi.fn()}
        selectedStage={stageName}
        stages={stages}
      />,
    );

    expect(screen.getByText(expectedLabel, { selector: ".ny-overview__progress-label" })).toBeVisible();
    expect(screen.queryByText(/APP_DEEPSEEK_API_KEY|Authorization|Bearer|prompt/i)).not.toBeInTheDocument();
  });

  it("renders the selected safe preparation summary when no live progress exists", () => {
    renderWorkstation(
      <StageRail
        executionProgress={null}
        onSelectStage={vi.fn()}
        selectedStage="media_prep"
        stages={[
          { attempts: 1, failure_code: null, finished_at: null, name: "media_prep", planned: false, started_at: null, status: "running", summary: "Prepared 5 audio chunks" },
        ]}
      />,
    );

    expect(screen.getByText("Prepared 5 audio chunks", { selector: ".ny-overview__stage-message" })).toBeVisible();
  });
});
