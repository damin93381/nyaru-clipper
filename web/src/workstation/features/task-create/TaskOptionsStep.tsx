import { CircleAlert, SlidersHorizontal } from "lucide-react";
import type { ReactNode } from "react";

import type { ProcessingProfile } from "./api";

interface TaskOptionsStepProps {
  readonly errors: Readonly<Partial<Record<"priority" | "profile_id" | "source", string>>>;
  readonly highlightFilteringEnabled: boolean;
  readonly onHighlightFilteringChange: (enabled: boolean) => void;
  readonly onPriorityChange: (priority: number) => void;
  readonly onProfileChange: (profileId: string) => void;
  readonly priority: number;
  readonly profileId: string;
  readonly profiles: readonly ProcessingProfile[];
}

export function TaskOptionsStep({ errors, highlightFilteringEnabled, onHighlightFilteringChange, onPriorityChange, onProfileChange, priority, profileId, profiles }: TaskOptionsStepProps): ReactNode {
  return (
    <div className="ny-task-create__step">
      <label className="ny-field" htmlFor="task-create-profile">处理配置<select aria-describedby={errors.profile_id === undefined ? undefined : "task-create-profile-error"} aria-invalid={errors.profile_id === undefined ? undefined : true} className={`ny-input${errors.profile_id === undefined ? "" : " ny-input--invalid"}`} id="task-create-profile" onChange={(event) => onProfileChange(event.target.value)} value={profileId}>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.stages.length} 个阶段</option>)}</select></label>
      {errors.profile_id === undefined ? null : <p className="ny-field__message ny-field__message--error" id="task-create-profile-error"><CircleAlert aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{errors.profile_id}</p>}
      <label className="ny-task-create__option"><input aria-label="启用自动高光筛选" checked={highlightFilteringEnabled} onChange={(event) => onHighlightFilteringChange(event.target.checked)} type="checkbox" /><span><strong>启用自动高光筛选</strong><span>生成排名候选片段；默认关闭以节省处理资源。</span></span></label>
      <label className="ny-field" htmlFor="task-create-priority">优先级<input aria-describedby={errors.priority === undefined ? undefined : "task-create-priority-error"} aria-invalid={errors.priority === undefined ? undefined : true} className={`ny-input${errors.priority === undefined ? "" : " ny-input--invalid"}`} id="task-create-priority" max="100" min="-100" onChange={(event) => onPriorityChange(Number(event.target.value))} step="1" type="number" value={priority} /></label>
      {errors.priority === undefined ? <p className="ny-field__message"><SlidersHorizontal aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />数字越高越靠前；同优先级仍遵循手动队列顺序。</p> : <p className="ny-field__message ny-field__message--error" id="task-create-priority-error"><CircleAlert aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{errors.priority}</p>}
      {errors.source === undefined ? null : <p className="ny-field__message ny-field__message--error"><CircleAlert aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{errors.source}</p>}
    </div>
  );
}
