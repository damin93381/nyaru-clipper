import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createTask } from "../lib/api";
import { NEW_TASK_COPY, NEW_TASK_PROCESSING_OPTIONS } from "../lib/copy";

export function NewTaskPage() {
	const { hero, form } = NEW_TASK_COPY;
	const navigate = useNavigate();
	const [sourceUrl, setSourceUrl] = useState("");
	const [options, setOptions] = useState<Record<string, boolean>>(() =>
		NEW_TASK_PROCESSING_OPTIONS.reduce<Record<string, boolean>>(
			(accumulator, option) => {
				accumulator[option.key] = option.defaultChecked;
				return accumulator;
			},
			{},
		),
	);

	const submitTaskMutation = useMutation({
		mutationFn: createTask,
		onSuccess: (task) => {
			navigate(`/tasks/${task.task_id}`);
		},
	});

	const optionSummary = useMemo(
		() =>
			NEW_TASK_PROCESSING_OPTIONS.filter((option) => options[option.key])
				.map((option) => option.label)
				.join(", "),
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

	const errorMessage =
		submitTaskMutation.error instanceof Error
			? submitTaskMutation.error.message
			: null;

	return (
		<section className="page page-grid">
			<div className="panel page-hero">
				<p className="eyebrow">{hero.eyebrow}</p>
				<h2>{hero.title}</h2>
				<p>{hero.description}</p>
			</div>

			<form className="panel task-form" onSubmit={handleSubmit}>
				<div className="panel__header">
					<div>
						<p className="eyebrow">{form.eyebrow}</p>
						<h3>{form.title}</h3>
					</div>
					<span className="status-badge status-badge--pending">
						{form.badge}
					</span>
				</div>

				<label className="field" htmlFor="task-url-input">
					<span className="field__label">{form.sourceUrlLabel}</span>
					<input
						className="field__input"
						data-testid="task-url-input"
						id="task-url-input"
						name="sourceUrl"
						onChange={(event) => setSourceUrl(event.target.value)}
						placeholder={form.sourceUrlPlaceholder}
						required
						type="url"
						value={sourceUrl}
					/>
				</label>

				<section
					className="task-form__options"
					aria-labelledby="processing-options-heading"
				>
					<div>
						<p className="eyebrow">{form.reservedControlsEyebrow}</p>
						<h4 id="processing-options-heading">
							{form.processingOptionsTitle}
						</h4>
						<p className="support-copy">{form.processingOptionsDescription}</p>
					</div>

					<div className="toggle-grid">
						{NEW_TASK_PROCESSING_OPTIONS.map((option) => (
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
						<span className="summary-strip__label">
							{form.summary.stagesLabel}
						</span>
						<strong>{optionSummary || form.summary.emptySelection}</strong>
					</div>
					<div>
						<span className="summary-strip__label">
							{form.summary.navigationLabel}
						</span>
						<strong>{form.summary.navigationDescription}</strong>
					</div>
				</div>

				{errorMessage ? <p className="form-error">{errorMessage}</p> : null}

				<button
					className="primary-button"
					data-testid="task-submit-button"
					disabled={submitTaskMutation.isPending}
					type="submit"
				>
					{submitTaskMutation.isPending ? form.submitPending : form.submitIdle}
				</button>
			</form>
		</section>
	);
}
