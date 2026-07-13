import * as Dialog from "@radix-ui/react-dialog";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Toast from "@radix-ui/react-toast";
import * as Tooltip from "@radix-ui/react-tooltip";
import { AlertTriangle, CircleAlert, CircleCheck, CircleX, LoaderCircle, Menu, PanelRightOpen, Play, X } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import "../design/tokens.css";
import "../design/global.css";
import "../design/primitives.css";

const stages = ["采集", "媒体准备", "语音识别", "翻译", "高光片段", "导出", "报告"] as const;
const progressClasses = ["complete", "complete", "running", "warning", "failed", "pending", "pending"] as const;

type FeedbackTone = "loading" | "empty" | "disconnected" | "failure";
type StampTone = "running" | "success" | "warning" | "failed";

const stampIcons: Record<StampTone, typeof LoaderCircle> = {
  running: LoaderCircle,
  success: CircleCheck,
  warning: AlertTriangle,
  failed: CircleX,
};

function StatusStamp({ label, tone }: { readonly label: string; readonly tone: StampTone }): ReactNode {
  const Icon = stampIcons[tone];

  return (
    <span className={`ny-stamp ny-stamp--${tone}`}>
      <Icon aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />
      {label}
    </span>
  );
}

function FeedbackPanel({ title, copy, tone }: { readonly title: string; readonly copy: string; readonly tone: FeedbackTone }): ReactNode {
  return (
    <section className={`ny-feedback ny-feedback--${tone}`} aria-label={title}>
      <p className="ny-feedback__title">{title}</p>
      <p className="ny-feedback__copy">{copy}</p>
    </section>
  );
}

export function PrimitiveShowcasePage(): ReactNode {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const announce = (message: string) => setToastMessage(message);

  return (
    <Toast.Provider duration={5000}>
      <main className="ny-showcase">
        <p className="ny-showcase__eyebrow">Nyaru-Clipper / foundation</p>
        <h1 className="ny-showcase__heading">工作台原语</h1>
        <p className="ny-showcase__copy">以纸面与墨色呈现的状态，让密集的操作表格仍然清晰、可恢复。</p>

        <section className="ny-showcase__section" aria-labelledby="buttons-heading">
          <h2 className="ny-showcase__section-heading" id="buttons-heading">按钮</h2>
          <div className="ny-showcase__cluster">
            <button className="ny-button ny-button--primary" type="button" onClick={() => announce("已开始媒体准备")}> <Play aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />开始媒体准备</button>
            <button className="ny-button" type="button" onClick={() => announce("已保存当前筛选条件")}>保存筛选条件</button>
            <button className="ny-button ny-button--quiet" type="button" onClick={() => announce("已展开辅助说明")}>展开辅助说明</button>
            <button className="ny-button" type="button" disabled>不可用操作</button>
            <button className="ny-button ny-button--danger" type="button" onClick={() => announce("已标记为待删除，请在确认框中继续")}>标记删除</button>
          </div>
        </section>

        <section className="ny-showcase__section" aria-labelledby="inputs-heading">
          <h2 className="ny-showcase__section-heading" id="inputs-heading">输入框</h2>
          <label className="ny-field">任务标题<input aria-describedby="task-title-help" className="ny-input" defaultValue="夏日档案：第七次直播" name="task-title" /></label>
          <p className="ny-field__message" id="task-title-help">标题需要能让操作员在任务表中快速辨认。</p>
          <label className="ny-field">需要修正的标题<input aria-describedby="task-title-error" aria-invalid="true" className="ny-input ny-input--invalid" defaultValue="" name="invalid-task-title" /></label>
          <p className="ny-field__message ny-field__message--error" id="task-title-error">标题不能为空，请填写能辨认该场直播的名称。</p>
          <label className="ny-field">已锁定的视频源<input className="ny-input" defaultValue="Bilibili 已结束直播" disabled name="source" /></label>
        </section>

        <section className="ny-showcase__section" aria-labelledby="stamps-heading">
          <h2 className="ny-showcase__section-heading" id="stamps-heading">状态印记</h2>
          <div className="ny-showcase__status-row"><StatusStamp label="处理中" tone="running" /><StatusStamp label="已完成" tone="success" /><StatusStamp label="需要注意" tone="warning" /><StatusStamp label="已失败" tone="failed" /></div>
        </section>

        <section className="ny-showcase__section" aria-labelledby="progress-heading">
          <h2 className="ny-showcase__section-heading" id="progress-heading">进度轨道</h2>
          <ol className="ny-progress" aria-label="流水线进度">
            {stages.map((stage, index) => {
              const tone = progressClasses[index];
              const selected = tone === "warning";
              const stateLabel = tone === "running" ? "处理中" : tone === "warning" ? "需要注意" : tone === "failed" ? "已失败" : null;
              return <li aria-current={selected ? "step" : undefined} className={`ny-progress__stage ny-progress__stage--${tone}`} data-selected={selected || undefined} key={stage}>{stage}{stateLabel ? ` · ${stateLabel}` : ""}</li>;
            })}
          </ol>
        </section>

        <section className="ny-showcase__section" aria-labelledby="rows-heading">
          <h2 className="ny-showcase__section-heading" id="rows-heading">表格行状态</h2>
          <table className="ny-table"><thead><tr><th>项目</th><th>状态</th><th>运行时间</th><th>操作</th></tr></thead><tbody>
            <tr aria-selected="true" className="ny-table__row--selected" tabIndex={0}><td>夏日档案：第七次直播</td><td><StatusStamp label="处理中" tone="running" /></td><td className="ny-table__technical">03:42:18</td><td><button className="ny-table__action" type="button" onClick={() => announce("已打开夏日档案任务")}>查看夏日档案任务</button></td></tr>
            <tr><td>雨后剪辑：最终导出</td><td><StatusStamp label="已完成" tone="success" /></td><td className="ny-table__technical">00:14:02</td><td><button className="ny-table__action" type="button" onClick={() => announce("已打开最终导出")}>查看最终导出</button></td></tr>
            <tr className="ny-table__row--warning" data-state="warning"><td>需要人工复核：翻译术语</td><td><StatusStamp label="需要注意" tone="warning" /></td><td className="ny-table__technical">00:00:48</td><td><button className="ny-table__action" type="button" onClick={() => announce("已打开翻译术语复核")}>查看复核任务</button></td></tr>
            <tr className="ny-table__row--failed" data-state="failed"><td>导出编码失败：等待恢复</td><td><StatusStamp label="已失败" tone="failed" /></td><td className="ny-table__technical">00:00:16</td><td><button className="ny-table__action" type="button" onClick={() => announce("已打开失败的导出任务")}>查看失败的导出任务</button></td></tr>
          </tbody></table>
        </section>

        <section className="ny-showcase__section" aria-labelledby="overlays-heading">
          <h2 className="ny-showcase__section-heading" id="overlays-heading">浮层</h2>
          <div className="ny-showcase__cluster">
            <Dialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}><Dialog.Trigger asChild><button className="ny-button" type="button"><PanelRightOpen aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />打开侧栏</button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="ny-dialog-overlay" /><Dialog.Content className="ny-overlay ny-drawer"><Dialog.Title className="ny-overlay__title">新建任务</Dialog.Title><Dialog.Description className="ny-overlay__description">保留当前表格选择，在右侧补充直播地址与处理偏好。</Dialog.Description><div className="ny-overlay__actions"><button className="ny-button ny-button--primary" type="button" onClick={() => { announce("已保存新任务草稿"); setDrawerOpen(false); }}>保存草稿</button><Dialog.Close asChild><button className="ny-button" type="button">关闭侧栏</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
            <Dialog.Root open={dialogOpen} onOpenChange={setDialogOpen}><Dialog.Trigger asChild><button className="ny-button ny-button--danger" type="button">打开确认对话框</button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="ny-dialog-overlay" /><Dialog.Content className="ny-overlay ny-dialog"><Dialog.Title className="ny-overlay__title">删除派生产物？</Dialog.Title><Dialog.Description className="ny-overlay__description">这会移除字幕、音频和导出片段；原始任务记录会被保留。</Dialog.Description><div className="ny-overlay__actions"><Dialog.Close asChild><button className="ny-button" type="button">取消</button></Dialog.Close><button className="ny-button ny-button--danger" type="button" onClick={() => { announce("已删除派生产物"); setDialogOpen(false); }}>删除派生产物</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
            <DropdownMenu.Root open={menuOpen} onOpenChange={setMenuOpen}><DropdownMenu.Trigger asChild><button className="ny-button" type="button" onClick={() => setMenuOpen(true)}><Menu aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />打开操作菜单</button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content align="start" className="ny-menu ny-menu--content" sideOffset={8}><DropdownMenu.Item className="ny-menu-item" onSelect={() => announce("任务已归档")}>归档任务</DropdownMenu.Item><DropdownMenu.Item className="ny-menu-item" onSelect={() => announce("已复制处理配置")}>复制处理配置</DropdownMenu.Item></DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>
            <Tooltip.Provider delayDuration={0}><Tooltip.Root><Tooltip.Trigger asChild><button className="ny-button" type="button">显示提示</button></Tooltip.Trigger><Tooltip.Portal><Tooltip.Content className="ny-menu ny-tooltip" sideOffset={8}>键盘焦点会保留在当前行。<Tooltip.Arrow className="ny-tooltip__arrow" /></Tooltip.Content></Tooltip.Portal></Tooltip.Root></Tooltip.Provider>
            <button className="ny-button" type="button" onClick={() => announce("队列顺序已保存")}>保存队列顺序</button>
          </div>
        </section>

        <section className="ny-showcase__section" aria-labelledby="feedback-heading">
          <h2 className="ny-showcase__section-heading" id="feedback-heading">反馈状态</h2>
          <div className="ny-showcase__feedback-grid"><FeedbackPanel title="正在读取任务元数据" copy="正在取得最新的任务快照。" tone="loading" /><FeedbackPanel title="此视图没有匹配任务" copy="清除筛选条件或新建任务。" tone="empty" /><FeedbackPanel title="连接暂时中断" copy="当前显示最近一次保存的工作台状态。" tone="disconnected" /><FeedbackPanel title="字幕准备失败" copy="查看恢复操作后再决定是否重试。" tone="failure" /></div>
        </section>
      </main>
      <Toast.Root className="ny-toast" open={toastMessage !== null} onOpenChange={(open) => { if (!open) setToastMessage(null); }}>
        <Toast.Title className="ny-overlay__title"><CircleAlert aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{toastMessage}</Toast.Title>
        <Toast.Description className="ny-overlay__description">这里只演示原语反馈，不会修改任务。</Toast.Description>
        <Toast.Close aria-label="关闭通知" className="ny-toast__close"><X aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" /></Toast.Close>
      </Toast.Root>
      <Toast.Viewport className="ny-toast-viewport" />
    </Toast.Provider>
  );
}
