import { type FormEvent, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { createTask } from "../lib/api";

interface ProcessingOption {
  key: string;
  label: string;
  helpText: string;
  defaultChecked: boolean;
}

const PROCESSING_OPTIONS: ProcessingOption[] = [
  {
    key: "translation",
    label: "Translation",
    helpText: "Keep bilingual subtitle generation in the visible workstation contract.",
    defaultChecked: true,
  },
  {
    key: "highlight",
    label: "Highlight",
    helpText: "Preserve highlight analysis as a tracked stage, even when no clips are found.",
    defaultChecked: true,
  },
  {
    key: "export",
    label: "Export",
    helpText: "Reserve clip/report export visibility; clip creation still requires later confirmation.",
    defaultChecked: true,
  },
] as const;

export function NewTaskPage() {
  const navigate = useNavigate();
  const [sourceUrl, setSourceUrl] = useState("");
  const [options, setOptions] = useState<Record<string, boolean>>(() =>
    PROCESSING_OPTIONS.reduce<Record<string, boolean>>((accumulator, option) => {
      accumulator[option.key] = option.defaultChecked;
      return accumulator;
    }, {}),
  );

  const submitTaskMutation = useMutation({
    mutationFn: createTask,
    onSuccess: (task) => {
      navigate(`/tasks/${task.task_id}`);
    },
  });

  const optionSummary = useMemo(
    () => PROCESSING_OPTIONS.filter((option) => options[option.key]).map((option) => option.label).join(", "),
    [options],
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!sourceUrl.trim()) {
      return;
    }

    submitTaskMutation.mutate({
      source_url: sourceUrl.trim(),
    });
  }

  function toggleOption(optionKey: string) {
    setOptions((current) => ({
      ...current,
      [optionKey]: !current[optionKey],
    }));
  }

  const errorMessage = submitTaskMutation.error instanceof Error ? submitTaskMutation.error.message : null;

  return (
    <section className="page page-grid">
      <div className="panel page-hero">
        <p className="eyebrow">Task intake</p>
        <h2>Queue a Bilibili VOD for the canonical workstation pipeline</h2>
        <p>
          Submit one completed VOD URL, keep the canonical stages visible, and land on the detail page that later expands
          into subtitle/highlight review.
        </p>
      </div>

      <form className="panel task-form" onSubmit={handleSubmit}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">New task</p>
            <h3>Create a task</h3>
          </div>
          <span className="status-badge status-badge--pending">Single-task MVP</span>
        </div>

        <label className="field" htmlFor="task-url-input">
          <span className="field__label">Bilibili VOD URL</span>
          <input
            className="field__input"
            data-testid="task-url-input"
            id="task-url-input"
            name="sourceUrl"
            onChange={(event) => setSourceUrl(event.target.value)}
            placeholder="https://www.bilibili.com/video/BV1xx411c7mD"
            required
            type="url"
            value={sourceUrl}
          />
        </label>

        <section className="task-form__options" aria-labelledby="processing-options-heading">
          <div>
            <p className="eyebrow">Reserved controls</p>
            <h4 id="processing-options-heading">Visible processing options</h4>
            <p className="support-copy">
              These toggles reserve room for future per-task controls while the MVP backend still runs the canonical staged
              pipeline.
            </p>
          </div>

          <div className="toggle-grid">
            {PROCESSING_OPTIONS.map((option) => (
              <label className="toggle-card" key={option.key}>
                <input
                  checked={options[option.key]}
                  className="toggle-card__input"
                  onChange={() => toggleOption(option.key)}
                  type="checkbox"
                />
                <span className="toggle-card__body">
                  <span className="toggle-card__label">{option.label}</span>
                  <span className="toggle-card__help">{option.helpText}</span>
                </span>
              </label>
            ))}
          </div>
        </section>

        <div className="summary-strip">
          <div>
            <span className="summary-strip__label">Visible stages</span>
            <strong>{optionSummary || "None selected"}</strong>
          </div>
          <div>
            <span className="summary-strip__label">Navigation</span>
            <strong>Successful submission goes straight to `/tasks/&lt;id&gt;`.</strong>
          </div>
        </div>

        {errorMessage ? <p className="form-error">{errorMessage}</p> : null}

        <button className="primary-button" data-testid="task-submit-button" disabled={submitTaskMutation.isPending} type="submit">
          {submitTaskMutation.isPending ? "Creating task..." : "Create task"}
        </button>
      </form>
    </section>
  );
}
