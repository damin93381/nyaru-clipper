import { Download, RotateCcw } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { downloadAsrModels, retryTaskFromStage } from "../../../lib/api";
import { formatStageLabel, type TaskStageName } from "../../../lib/types";
import { workstationKeys } from "../../api/queryKeys";
import type { WorkstationTaskOverview } from "./api";

interface RecoveryPanelProps {
  readonly actions: WorkstationTaskOverview["recovery_actions"];
  readonly taskId: string;
}

function legacyStageName(value: string): TaskStageName | null {
  switch (value) {
    case "ingest": return "ingest";
    case "media_prep": return "media_prep";
    case "asr": return "asr";
    case "translation": return "translation";
    case "highlight": return "highlight";
    case "export": return "export";
    case "report": return "report";
    default: return null;
  }
}

export function RecoveryPanel({ actions, taskId }: RecoveryPanelProps): ReactNode {
  const queryClient = useQueryClient();
  const retryMutation = useMutation({
    mutationFn: (stageName: TaskStageName) => retryTaskFromStage(taskId, stageName),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: workstationKeys.detail(taskId) }),
  });
  const downloadMutation = useMutation({
    mutationFn: async (modelKeys: ("whisperx" | "alignment")[]) => {
      await downloadAsrModels(taskId, modelKeys);
      return retryTaskFromStage(taskId, "asr");
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: workstationKeys.detail(taskId) }),
  });

  if (actions.length === 0) return null;

  function retryStage(stageName: string): void {
    const stage = legacyStageName(stageName);
    if (stage !== null) retryMutation.mutate(stage);
  }

  return (
    <section className="ny-overview__recovery ny-feedback ny-feedback--failure" aria-labelledby="task-recovery-title">
      <p className="ny-workstation__eyebrow">恢复操作</p>
      <h2 className="ny-feedback__title" id="task-recovery-title">可恢复的问题</h2>
      <div className="ny-overview__recovery-actions">
        {actions.map((action) => {
          if (action.id === "download_asr_model") {
            return <button className="ny-button ny-button--primary" disabled={!action.enabled || downloadMutation.isPending || retryMutation.isPending} key={action.id} onClick={() => downloadMutation.mutate([...action.payload.model_keys])} type="button"><Download aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />下载缺失模型</button>;
          }
          return <button className="ny-button" disabled={!action.enabled || downloadMutation.isPending || retryMutation.isPending || legacyStageName(action.payload.stage_name) === null} key={action.id} onClick={() => retryStage(action.payload.stage_name)} type="button"><RotateCcw aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />从{formatStageLabel(action.payload.stage_name)}重新尝试</button>;
        })}
      </div>
      {retryMutation.isError || downloadMutation.isError ? <p className="ny-field__message ny-field__message--error" role="alert">恢复操作没有完成，请检查安全日志后重试。</p> : null}
    </section>
  );
}
