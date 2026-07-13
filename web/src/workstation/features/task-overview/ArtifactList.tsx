import { Download, FileText } from "lucide-react";
import type { ReactNode } from "react";

import { resolveArtifactUrl } from "../../../lib/api";
import type { WorkstationTaskOverview } from "./api";

interface ArtifactListProps {
  readonly artifacts: WorkstationTaskOverview["artifacts"];
  readonly selectedStage: string | null;
}

function artifactLabel(kind: string): string {
  switch (kind) {
    case "transcript_json": return "转写片段";
    case "bilingual_transcript_json": return "双语字幕数据";
    case "highlight_candidates_json": return "高光候选";
    case "clip_export": return "已导出片段";
    case "task_report_markdown": return "任务报告";
    default: return kind.replace(/_/g, " ");
  }
}

export function ArtifactList({ artifacts, selectedStage }: ArtifactListProps): ReactNode {
  const selectedArtifacts = selectedStage === null ? artifacts : artifacts.filter((artifact) => artifact.stage_name === selectedStage);
  return (
    <section className="ny-overview-inspector__section" aria-labelledby="task-artifact-list-title">
      <p className="ny-workstation__eyebrow">产物</p>
      <h2 className="ny-workstation__inspector-heading" id="task-artifact-list-title">{selectedStage ? "当前阶段产物" : "任务产物"}</h2>
      {selectedArtifacts.length === 0 ? <p className="ny-workstation-page__copy">当前阶段还没有可用产物。</p> : (
        <ul className="ny-overview-inspector__list">
          {selectedArtifacts.map((artifact) => (
            <li key={artifact.artifact_id}>
              <FileText aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />
              <span>{artifactLabel(artifact.kind)}</span>
              <a className="ny-overview-inspector__download" href={resolveArtifactUrl(artifact.path)}><Download aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />下载</a>
              <details className="ny-overview-inspector__technical"><summary>技术信息</summary><code>{artifact.path}</code></details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
