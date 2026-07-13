import { CircleAlert, Search } from "lucide-react";
import type { ReactNode } from "react";

interface BilibiliSourceStepProps {
  readonly error: string | undefined;
  readonly isInspecting: boolean;
  readonly onInspect: () => void;
  readonly onUrlChange: (url: string) => void;
  readonly url: string;
}

export function BilibiliSourceStep({ error, isInspecting, onInspect, onUrlChange, url }: BilibiliSourceStepProps): ReactNode {
  return (
    <div className="ny-task-create__step">
      <label className="ny-field" htmlFor="task-create-bilibili-url">
        Bilibili 链接
        <input
          aria-describedby={error === undefined ? "task-create-bilibili-help" : "task-create-bilibili-error"}
          aria-invalid={error === undefined ? undefined : true}
          className={`ny-input${error === undefined ? "" : " ny-input--invalid"}`}
          id="task-create-bilibili-url"
          onChange={(event) => onUrlChange(event.target.value)}
          placeholder="https://www.bilibili.com/video/BV…"
          value={url}
        />
      </label>
      {error === undefined ? <p className="ny-field__message" id="task-create-bilibili-help">先检查已结束录播，再确认要进入队列的来源。</p> : <p className="ny-field__message ny-field__message--error" id="task-create-bilibili-error"><CircleAlert aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{error}</p>}
      <button className="ny-button ny-button--primary" disabled={isInspecting} onClick={onInspect} type="button"><Search aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{isInspecting ? "正在检查来源" : "检查来源"}</button>
    </div>
  );
}
