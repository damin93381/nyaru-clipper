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

type CardTone = "healthy" | "warning" | "danger";

function getStatusLabel(status: RuntimeCapabilityStatus): string {
  switch (status) {
    case "ok":
      return "Healthy";
    case "warning":
      return "Warning";
    case "error":
      return "Error";
  }
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

function getCardTone(status: RuntimeCapabilityStatus): CardTone {
  switch (status) {
    case "ok":
      return "healthy";
    case "warning":
      return "warning";
    case "error":
      return "danger";
  }
}

function describeAcceleration(capabilities: RuntimeCapabilities): string {
  const { accelerator } = capabilities;
  if (!accelerator.available) {
    if (accelerator.torch_build_family && accelerator.torch_build_family !== "unknown") {
      return `No accelerator detected · torch ${accelerator.torch_build_family} build`;
    }
    return "No accelerator detected";
  }

  const deviceLabel = accelerator.device_count === 1 ? "device" : "devices";
  const deviceName = accelerator.device_name ? ` · ${accelerator.device_name}` : "";
  const buildFamily = accelerator.torch_build_family ? ` · torch ${accelerator.torch_build_family}` : "";
  return `${accelerator.backend} · ${accelerator.device_count} ${deviceLabel}${deviceName}${buildFamily}`;
}

function hasIssue(capabilities: RuntimeCapabilities, code: string): boolean {
  return capabilities.issues.some((issue) => issue.code === code);
}

function getPrimaryMessage(capabilities: RuntimeCapabilities, fullFunctionSatisfied: boolean): string {
  if (fullFunctionSatisfied) {
    return "Runtime checks report the expected full-function profile for this workstation.";
  }

  if (hasIssue(capabilities, "wrong_torch_build_cuda_on_wsl")) {
    return "This WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm runtime.";
  }

  return "This environment does not currently satisfy the expected full-function profile.";
}

function getSupportMessage(capabilities: RuntimeCapabilities, fullFunctionSatisfied: boolean): string {
  if (fullFunctionSatisfied) {
    return "GPU-backed processing is available for the active runtime profile.";
  }

  if (hasIssue(capabilities, "wrong_torch_build_cuda_on_wsl")) {
    return "Use the dedicated WSL ROCm backend environment so startup stays non-blocking while operators still see the exact wheel mismatch.";
  }

  return "Warnings do not block task submission or task review, but they may reduce processing capability.";
}

export function EnvironmentStatusCard({
  capabilities,
  errorMessage,
  isLoading = false,
}: EnvironmentStatusCardProps) {
  if (isLoading && !capabilities && !errorMessage) {
    return (
      <section
        aria-live="polite"
        className="panel environment-status-card environment-status-card--loading"
        data-testid="environment-status-card"
      >
        <p className="eyebrow">Environment status</p>
        <h2>Environment status</h2>
        <p>Checking backend runtime capabilities for the active workstation profile.</p>
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
            <p className="eyebrow">Environment status</p>
            <h2>Environment status</h2>
          </div>
          <div className="environment-status-card__badges">
            <span className="status-badge status-badge--warning">Unavailable</span>
            <span className="pill">Needs attention</span>
          </div>
        </div>
        <p>
          Runtime capability checks are temporarily unavailable. Existing task views remain available while the shell
          retries later.
        </p>
        {errorMessage ? <p className="environment-status-card__detail">{errorMessage}</p> : null}
      </section>
    );
  }

  const fullFunctionSatisfied = satisfiesFullFunctionProfile(capabilities);
  const tone = getCardTone(capabilities.status);
  const primaryMessage = getPrimaryMessage(capabilities, fullFunctionSatisfied);
  const supportCopy = getSupportMessage(capabilities, fullFunctionSatisfied);

  return (
    <section
      aria-live="polite"
      className={`panel environment-status-card environment-status-card--${tone}`}
      data-testid="environment-status-card"
    >
      <div className="environment-status-card__header">
        <div>
          <p className="eyebrow">Environment status</p>
          <h2>Environment status</h2>
        </div>
        <div className="environment-status-card__badges">
          <span className={getStatusBadgeClass(capabilities.status)}>{getStatusLabel(capabilities.status)}</span>
          <span className="pill">{fullFunctionSatisfied ? "Satisfied" : "Needs attention"}</span>
        </div>
      </div>

      <p>{primaryMessage}</p>
      <p className="environment-status-card__detail">{supportCopy}</p>

      <dl className="metadata-list environment-status-card__metadata">
        <div className="metadata-list__row">
          <dt>Active profile</dt>
          <dd>{capabilities.detected_profile}</dd>
        </div>
        <div className="metadata-list__row">
          <dt>Acceleration</dt>
          <dd>{describeAcceleration(capabilities)}</dd>
        </div>
      </dl>

      {capabilities.warnings.length > 0 ? (
        <div className="environment-status-card__warnings">
          <h3>Active warnings</h3>
          <ul className="placeholder-list environment-status-card__warning-list">
            {capabilities.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {capabilities.issues.length > 0 ? (
        <div className="environment-status-card__warnings">
          <h3>Detected issues</h3>
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
