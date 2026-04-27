import {
  describeEnvironmentAcceleration,
  ENVIRONMENT_STATUS_COPY,
  getEnvironmentCardTone,
  getEnvironmentPrimaryMessage,
  getEnvironmentStatusBadgeLabel,
  getEnvironmentSupportMessage,
} from "../lib/copy/environmentStatus";
import {
  type RuntimeCapabilities,
  type RuntimeCapabilityStatus,
  satisfiesFullFunctionProfile,
} from "../lib/types";

interface EnvironmentStatusCardProps {
  capabilities?: RuntimeCapabilities | null;
  errorMessage?: string | null;
  isLoading?: boolean;
}

function getStatusBadgeClass(status: RuntimeCapabilityStatus): string {
  switch (status) {
    case "ok":
      return "status-badge status-badge--success";
    case "warning":
      return "status-badge status-badge--warning";
    case "error":
      return "status-badge status-badge--failed";
  }
}

export function EnvironmentStatusCard({
  capabilities,
  errorMessage,
  isLoading = false,
}: EnvironmentStatusCardProps) {
  const {
    attentionBadge,
    card,
    loading,
    metadata,
    sections,
    satisfiedBadge,
    unavailable,
  } = ENVIRONMENT_STATUS_COPY;

  if (isLoading && !capabilities && !errorMessage) {
    return (
      <section
        aria-live="polite"
        className="panel environment-status-card environment-status-card--loading"
        data-testid="environment-status-card"
      >
        <p className="eyebrow">{card.eyebrow}</p>
        <h2>{card.title}</h2>
        <p>{loading.description}</p>
      </section>
    );
  }

  if (!capabilities) {
    return (
      <section
        aria-live="polite"
        className="panel environment-status-card environment-status-card--warning"
        data-testid="environment-status-card"
      >
        <div className="environment-status-card__header">
          <div>
            <p className="eyebrow">{card.eyebrow}</p>
            <h2>{card.title}</h2>
          </div>
          <div className="environment-status-card__badges">
            <span className="status-badge status-badge--warning">{unavailable.statusBadge}</span>
            <span className="pill">{unavailable.attentionBadge}</span>
          </div>
        </div>
        <p>{unavailable.description}</p>
        {errorMessage ? <p className="environment-status-card__detail">{errorMessage}</p> : null}
      </section>
    );
  }

  const fullFunctionSatisfied = satisfiesFullFunctionProfile(capabilities);
  const tone = getEnvironmentCardTone(capabilities.status);
  const primaryMessage = getEnvironmentPrimaryMessage(capabilities, fullFunctionSatisfied);
  const supportCopy = getEnvironmentSupportMessage(capabilities, fullFunctionSatisfied);

  return (
    <section
      aria-live="polite"
      className={`panel environment-status-card environment-status-card--${tone}`}
      data-testid="environment-status-card"
    >
      <div className="environment-status-card__header">
        <div>
          <p className="eyebrow">{card.eyebrow}</p>
          <h2>{card.title}</h2>
        </div>
        <div className="environment-status-card__badges">
          <span className={getStatusBadgeClass(capabilities.status)}>{getEnvironmentStatusBadgeLabel(capabilities.status)}</span>
          <span className="pill">{fullFunctionSatisfied ? satisfiedBadge : attentionBadge}</span>
        </div>
      </div>

      <p>{primaryMessage}</p>
      <p className="environment-status-card__detail">{supportCopy}</p>

      <dl className="metadata-list environment-status-card__metadata">
        <div className="metadata-list__row">
          <dt>{metadata.activeProfile}</dt>
          <dd>{capabilities.detected_profile}</dd>
        </div>
        <div className="metadata-list__row">
          <dt>{metadata.acceleration}</dt>
          <dd>{describeEnvironmentAcceleration(capabilities)}</dd>
        </div>
      </dl>

      {capabilities.warnings.length > 0 ? (
        <div className="environment-status-card__warnings">
          <h3>{sections.warnings}</h3>
          <ul className="placeholder-list environment-status-card__warning-list">
            {capabilities.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {capabilities.issues.length > 0 ? (
        <div className="environment-status-card__warnings">
          <h3>{sections.issues}</h3>
          <ul className="placeholder-list environment-status-card__warning-list">
            {capabilities.issues.map((issue) => (
              <li key={issue.code}>{issue.message}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
