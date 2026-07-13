import * as Dialog from "@radix-ui/react-dialog";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Toast from "@radix-ui/react-toast";
import * as Tooltip from "@radix-ui/react-tooltip";
import { AlertTriangle, CircleAlert, CircleCheck, CircleX, LoaderCircle, Menu, PanelRightOpen, Play } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import "../design/tokens.css";
import "../design/global.css";
import "../design/primitives.css";

const stages = ["Ingest", "Media prep", "ASR", "Translate", "Highlights", "Export", "Report"] as const;
const progressClasses = ["complete", "complete", "complete", "running", "pending", "pending", "pending"] as const;

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
  const [toastOpen, setToastOpen] = useState(false);

  return (
    <Toast.Provider>
      <main className="ny-showcase">
        <p className="ny-showcase__eyebrow">Nyaru-Clipper / foundation</p>
        <h1 className="ny-showcase__heading">Workstation primitives</h1>
        <p className="ny-showcase__copy">The paper-and-ink states that make a dense operations table readable and recoverable.</p>

        <section className="ny-showcase__section" aria-labelledby="buttons-heading">
          <h2 className="ny-showcase__section-heading" id="buttons-heading">Buttons</h2>
          <div className="ny-showcase__cluster">
            <button className="ny-button ny-button--primary" type="button"><Play aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />Primary action</button>
            <button className="ny-button" type="button">Secondary action</button>
            <button className="ny-button" type="button" disabled>Disabled action</button>
            <button className="ny-button ny-button--danger" type="button">Destructive action</button>
          </div>
        </section>

        <section className="ny-showcase__section" aria-labelledby="inputs-heading">
          <h2 className="ny-showcase__section-heading" id="inputs-heading">Inputs</h2>
          <label className="ny-field">Task title<input className="ny-input" defaultValue="A Quiet Summer Archive" name="task-title" /></label>
          <label className="ny-field">Disabled source<input className="ny-input" defaultValue="Bilibili VOD" disabled name="source" /></label>
        </section>

        <section className="ny-showcase__section" aria-labelledby="stamps-heading">
          <h2 className="ny-showcase__section-heading" id="stamps-heading">Status stamps</h2>
          <div className="ny-showcase__status-row"><StatusStamp label="Running" tone="running" /><StatusStamp label="Succeeded" tone="success" /><StatusStamp label="Needs attention" tone="warning" /><StatusStamp label="Failed" tone="failed" /></div>
        </section>

        <section className="ny-showcase__section" aria-labelledby="progress-heading">
          <h2 className="ny-showcase__section-heading" id="progress-heading">Progress rail</h2>
          <ol className="ny-progress" aria-label="Pipeline progress">
            {stages.map((stage, index) => <li className={`ny-progress__stage ny-progress__stage--${progressClasses[index]}`} key={stage}>{stage}</li>)}
          </ol>
        </section>

        <section className="ny-showcase__section" aria-labelledby="rows-heading">
          <h2 className="ny-showcase__section-heading" id="rows-heading">Table row states</h2>
          <table className="ny-table"><thead><tr><th>Project</th><th>Status</th><th>Run</th></tr></thead><tbody>
            <tr aria-selected="true"><td>Selected task</td><td><StatusStamp label="Running" tone="running" /></td><td className="ny-table__technical">03:42:18</td></tr>
            <tr><td>Reviewed export</td><td><StatusStamp label="Succeeded" tone="success" /></td><td className="ny-table__technical">00:14:02</td></tr>
            <tr><td>Repair required</td><td><StatusStamp label="Failed" tone="failed" /></td><td className="ny-table__technical">00:00:48</td></tr>
          </tbody></table>
        </section>

        <section className="ny-showcase__section" aria-labelledby="overlays-heading">
          <h2 className="ny-showcase__section-heading" id="overlays-heading">Overlays</h2>
          <div className="ny-showcase__cluster">
            <Dialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}><Dialog.Trigger asChild><button className="ny-button" type="button"><PanelRightOpen aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />Open drawer</button></Dialog.Trigger><Dialog.Portal><Dialog.Content className="ny-overlay ny-drawer"><Dialog.Title className="ny-overlay__title">New task</Dialog.Title><Dialog.Description className="ny-overlay__description">Keep the current table selection in context while preparing a source.</Dialog.Description><Dialog.Close asChild><button className="ny-button" type="button">Close drawer</button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
            <Dialog.Root open={dialogOpen} onOpenChange={setDialogOpen}><Dialog.Trigger asChild><button className="ny-button ny-button--danger" type="button">Open confirmation dialog</button></Dialog.Trigger><Dialog.Portal><Dialog.Content className="ny-overlay ny-dialog"><Dialog.Title className="ny-overlay__title">Delete managed artifacts?</Dialog.Title><Dialog.Description className="ny-overlay__description">This removes derived files but preserves the original task record.</Dialog.Description><div className="ny-overlay__actions"><Dialog.Close asChild><button className="ny-button" type="button">Cancel</button></Dialog.Close><Dialog.Close asChild><button className="ny-button ny-button--danger" type="button">Delete artifacts</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
            <DropdownMenu.Root><DropdownMenu.Trigger asChild><button className="ny-button" type="button"><Menu aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />Open actions menu</button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="ny-menu"><DropdownMenu.Item className="ny-menu-item">Archive task</DropdownMenu.Item><DropdownMenu.Item className="ny-menu-item">Duplicate profile</DropdownMenu.Item></DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>
            <Tooltip.Provider><Tooltip.Root><Tooltip.Trigger asChild><button className="ny-button" type="button">Show tooltip</button></Tooltip.Trigger><Tooltip.Portal><Tooltip.Content className="ny-menu">Visible focus follows the selected table row.<Tooltip.Arrow /></Tooltip.Content></Tooltip.Portal></Tooltip.Root></Tooltip.Provider>
            <button className="ny-button" type="button" onClick={() => setToastOpen(true)}>Show toast</button>
          </div>
        </section>

        <section className="ny-showcase__section" aria-labelledby="feedback-heading">
          <h2 className="ny-showcase__section-heading" id="feedback-heading">Feedback states</h2>
          <div className="ny-showcase__feedback-grid"><FeedbackPanel title="Loading task metadata" copy="Reading the latest task snapshot." tone="loading" /><FeedbackPanel title="No tasks match this view" copy="Clear a filter or create a new task." tone="empty" /><FeedbackPanel title="Connection interrupted" copy="Showing the latest saved workspace state." tone="disconnected" /><FeedbackPanel title="Transcript preparation failed" copy="Review the recovery action before retrying." tone="failure" /></div>
        </section>
      </main>
      <Toast.Root className="ny-overlay" open={toastOpen} onOpenChange={setToastOpen}><Toast.Title className="ny-overlay__title"><CircleAlert aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />Queue order saved</Toast.Title><Toast.Description className="ny-overlay__description">The workstation will refresh its queue snapshot.</Toast.Description></Toast.Root>
      <Toast.Viewport />
    </Toast.Provider>
  );
}
