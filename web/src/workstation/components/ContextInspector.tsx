import { CircleDotDashed, ListChecks } from "lucide-react";
import { useParams } from "react-router-dom";
import type { ReactNode } from "react";

export function ContextInspector(): ReactNode {
  const { taskId } = useParams();
  const hasTaskContext = taskId !== undefined;

  return (
    <aside className="ny-workstation__inspector" aria-label="上下文检查器">
      <p className="ny-workstation__eyebrow">上下文</p>
      <h2 className="ny-workstation__inspector-heading">{hasTaskContext ? "已选择任务" : "工作台状态"}</h2>
      <div className="ny-workstation__inspector-state">
        {hasTaskContext ? <ListChecks aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" /> : <CircleDotDashed aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />}
        <p lang="zh-CN">
          {hasTaskContext ? (
            <>
              <span className="ny-workstation__inspector-task-reference">任务 {taskId}</span>
              的详细进度和恢复操作将
              <span className="ny-workstation__inspector-copy-phrase">
                在<span className="ny-workstation__inspector-copy-phrase">此处显示</span>
              </span>
              。
            </>
          ) : (
            <>
              从任务库选择一项，即可在
              <span className="ny-workstation__inspector-copy-phrase">
                不离开<span className="ny-workstation__inspector-copy-phrase">当前工作区</span>
                <span className="ny-workstation__inspector-copy-phrase">的情况下</span>
              </span>
              查看状态。
            </>
          )}
        </p>
      </div>
    </aside>
  );
}
