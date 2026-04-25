import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { exportTaskClip, fetchArtifactJson, resolveArtifactUrl } from "../lib/api";
import {
  humanizeSummary,
  safeParseMetadata,
  type ArtifactRecord,
  type ClipExportResponse,
  type HighlightArtifactPayload,
  type HighlightWorkspaceCandidate,
  type SubtitleArtifactPayload,
} from "../lib/types";

interface WorkspacePageProps {
  taskId: string;
  artifacts: ArtifactRecord[];
}

interface CandidateRangeState {
  start: string;
  end: string;
}

interface ExportedClipArtifact {
  id: number;
  filename: string;
  path: string;
  start_s: number;
  end_s: number;
  candidate_id: number;
}

interface SubtitleRow {
  id: string;
  startSeconds: number;
  endSeconds: number;
  chineseText: string;
  translatedText: string | null;
}

const DOWNLOADABLE_ARTIFACT_KINDS = new Set([
  "transcript_json",
  "subtitle_srt",
  "bilingual_transcript_json",
  "bilingual_subtitle_srt",
  "task_report_markdown",
  "clip_export",
]);

function findLatestArtifact(artifacts: ArtifactRecord[], kind: string): ArtifactRecord | null {
  return [...artifacts].reverse().find((artifact) => artifact.kind === kind) ?? null;
}

function getCandidateKey(candidate: HighlightWorkspaceCandidate): string {
  if (candidate.candidate_id !== undefined) {
    return `candidate-${candidate.candidate_id}`;
  }

  return `candidate-${candidate.rank}-${candidate.start_s}-${candidate.end_s}`;
}

function formatTimestamp(startSeconds: number, endSeconds: number): string {
  return `${startSeconds.toFixed(3)}s → ${endSeconds.toFixed(3)}s`;
}

function formatReason(reason: string): string {
  return humanizeSummary(reason);
}

function buildSubtitleRows(
  transcriptPayload: SubtitleArtifactPayload | undefined,
  bilingualPayload: SubtitleArtifactPayload | undefined,
): SubtitleRow[] {
  const sourceSegments = transcriptPayload?.segments?.length ? transcriptPayload.segments : bilingualPayload?.segments ?? [];
  const bilingualById = new Map((bilingualPayload?.segments ?? []).map((segment) => [segment.id, segment]));

  return sourceSegments.map((segment) => {
    const bilingualSegment = bilingualById.get(segment.id);

    return {
      id: segment.id,
      startSeconds: segment.start_seconds,
      endSeconds: segment.end_seconds,
      chineseText: segment.text || bilingualSegment?.text || "",
      translatedText: bilingualSegment?.translated_text ?? null,
    };
  });
}

function toExportedClipArtifact(artifact: ArtifactRecord): ExportedClipArtifact {
  const metadata = safeParseMetadata(artifact.metadata_json);
  const pathParts = artifact.path.split("/");
  const filename = pathParts[pathParts.length - 1] || artifact.path;

  return {
    id: artifact.id,
    filename,
    path: artifact.path,
    start_s: Number(metadata.start_s ?? 0),
    end_s: Number(metadata.end_s ?? 0),
    candidate_id: Number(metadata.candidate_id ?? 0),
  };
}

function toExportedClipArtifactFromResponse(response: ClipExportResponse): ExportedClipArtifact {
  return {
    id: response.artifact_id,
    filename: response.filename,
    path: response.path,
    start_s: response.start_s,
    end_s: response.end_s,
    candidate_id: response.candidate_id,
  };
}

function getDownloadLabel(kind: string): string {
  switch (kind) {
    case "subtitle_srt":
      return "Download Chinese subtitles";
    case "bilingual_subtitle_srt":
      return "Download bilingual subtitles";
    case "transcript_json":
      return "Download Chinese transcript JSON";
    case "bilingual_transcript_json":
      return "Download bilingual transcript JSON";
    case "task_report_markdown":
      return "Download task report";
    case "clip_export":
      return "Download exported clip";
    default:
      return `Download ${kind}`;
  }
}

export function WorkspacePage({ taskId, artifacts }: WorkspacePageProps) {
  const transcriptArtifact = useMemo(() => findLatestArtifact(artifacts, "transcript_json"), [artifacts]);
  const bilingualArtifact = useMemo(() => findLatestArtifact(artifacts, "bilingual_transcript_json"), [artifacts]);
  const highlightArtifact = useMemo(() => findLatestArtifact(artifacts, "highlight_candidates_json"), [artifacts]);
  const transcriptPath = transcriptArtifact?.path;
  const bilingualPath = bilingualArtifact?.path;
  const highlightPath = highlightArtifact?.path;

  const downloadArtifacts = useMemo(
    () => artifacts.filter((artifact) => DOWNLOADABLE_ARTIFACT_KINDS.has(artifact.kind)),
    [artifacts],
  );

  const persistedClipArtifacts = useMemo(
    () => artifacts.filter((artifact) => artifact.kind === "clip_export").map(toExportedClipArtifact),
    [artifacts],
  );

  const transcriptQuery = useQuery({
    queryKey: ["artifact", taskId, transcriptArtifact?.id],
    queryFn: () => fetchArtifactJson<SubtitleArtifactPayload>(transcriptPath ?? ""),
    enabled: Boolean(transcriptPath),
  });

  const bilingualQuery = useQuery({
    queryKey: ["artifact", taskId, bilingualArtifact?.id],
    queryFn: () => fetchArtifactJson<SubtitleArtifactPayload>(bilingualPath ?? ""),
    enabled: Boolean(bilingualPath),
  });

  const highlightQuery = useQuery({
    queryKey: ["artifact", taskId, highlightArtifact?.id],
    queryFn: () => fetchArtifactJson<HighlightArtifactPayload>(highlightPath ?? ""),
    enabled: Boolean(highlightPath),
  });

  const subtitleRows = useMemo(
    () => buildSubtitleRows(transcriptQuery.data, bilingualQuery.data),
    [bilingualQuery.data, transcriptQuery.data],
  );

  const [candidateRanges, setCandidateRanges] = useState<Record<string, CandidateRangeState>>({});
  const [localClipArtifacts, setLocalClipArtifacts] = useState<ExportedClipArtifact[]>([]);

  useEffect(() => {
    const candidates = highlightQuery.data?.candidates ?? [];
    if (candidates.length === 0) {
      return;
    }

    setCandidateRanges((current) => {
      const next = { ...current };
      let changed = false;

      for (const candidate of candidates) {
        const key = getCandidateKey(candidate);
        if (next[key]) {
          continue;
        }

        const defaultStart = candidate.default_range?.start_s ?? candidate.start_s;
        const defaultEnd = candidate.default_range?.end_s ?? candidate.end_s;
        next[key] = {
          start: String(defaultStart),
          end: String(defaultEnd),
        };
        changed = true;
      }

      return changed ? next : current;
    });
  }, [highlightQuery.data]);

  const exportClipMutation = useMutation({
    mutationFn: async (candidate: HighlightWorkspaceCandidate) => {
      if (candidate.candidate_id === undefined) {
        throw new Error("Candidate export is unavailable until a durable candidate_id is present.");
      }

      const range = candidateRanges[getCandidateKey(candidate)];
      const start_s = Number(range?.start ?? candidate.default_range?.start_s ?? candidate.start_s);
      const end_s = Number(range?.end ?? candidate.default_range?.end_s ?? candidate.end_s);

      return exportTaskClip(taskId, {
        candidate_id: candidate.candidate_id,
        start_s,
        end_s,
      });
    },
    onSuccess: (response) => {
      setLocalClipArtifacts((current) => {
        const nextArtifact = toExportedClipArtifactFromResponse(response);
        const withoutDuplicate = current.filter((artifact) => artifact.id !== nextArtifact.id);
        return [...withoutDuplicate, nextArtifact];
      });
    },
  });

  const exportedClipArtifacts = useMemo(() => {
    const artifactsById = new Map<number, ExportedClipArtifact>();
    for (const artifact of [...persistedClipArtifacts, ...localClipArtifacts]) {
      artifactsById.set(artifact.id, artifact);
    }
    return [...artifactsById.values()].sort((left, right) => left.id - right.id);
  }, [localClipArtifacts, persistedClipArtifacts]);

  const zeroCandidateMessage =
    highlightQuery.data?.no_candidates ??
    (highlightQuery.data && (highlightQuery.data.candidates?.length ?? 0) === 0
      ? "No highlight candidates cleared the current scoring threshold."
      : null);

  return (
    <section className="panel workspace-panel">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h3>Subtitle review and highlight confirmation</h3>
        </div>
        <span className="pill">Task 10 workspace</span>
      </div>

      <div className="workspace-layout">
        <section className="workspace-section">
          <div className="workspace-section__header">
            <div>
              <p className="eyebrow">Subtitles</p>
              <h4>Chinese and bilingual transcript rows</h4>
            </div>
          </div>

          {subtitleRows.length > 0 ? (
            <div className="subtitle-table">
              <div className="subtitle-table__header">
                <span>Segment</span>
                <span>Chinese subtitle</span>
                <span>Bilingual subtitle</span>
              </div>
              {subtitleRows.map((row) => (
                <div className="subtitle-row" key={row.id}>
                  <div className="subtitle-row__meta">
                    <strong>{row.id}</strong>
                    <span>{formatTimestamp(row.startSeconds, row.endSeconds)}</span>
                  </div>
                  <p>{row.chineseText}</p>
                  <p>{row.translatedText ?? "No bilingual translation available yet."}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="support-copy">Subtitle rows appear here once transcript artifacts are available.</p>
          )}
        </section>

        <section className="workspace-section">
          <div className="workspace-section__header">
            <div>
              <p className="eyebrow">Highlight candidates</p>
              <h4>Ranked candidate confirmation</h4>
            </div>
          </div>

          {highlightQuery.data?.candidates && highlightQuery.data.candidates.length > 0 ? (
            <ol className="candidate-list">
              {highlightQuery.data.candidates.map((candidate) => {
                const key = getCandidateKey(candidate);
                const range = candidateRanges[key] ?? {
                  start: String(candidate.default_range?.start_s ?? candidate.start_s),
                  end: String(candidate.default_range?.end_s ?? candidate.end_s),
                };

                return (
                  <li className="candidate-card" key={key}>
                    <div className="candidate-card__header">
                      <div>
                        <p className="stage-card__eyebrow">{`Rank ${candidate.rank}`}</p>
                        <h4>{`Score ${candidate.score.toFixed(2)}`}</h4>
                      </div>
                      <span className="pill">{formatTimestamp(candidate.start_s, candidate.end_s)}</span>
                    </div>

                    <div className="candidate-card__body">
                      <p>
                        <strong>Reasons:</strong>{" "}
                        {candidate.reasons.length > 0
                          ? candidate.reasons.map((reason) => formatReason(reason)).join(", ")
                          : "No reason codes available."}
                      </p>
                      <p>
                        <strong>Default range:</strong>{" "}
                        {formatTimestamp(
                          candidate.default_range?.start_s ?? candidate.start_s,
                          candidate.default_range?.end_s ?? candidate.end_s,
                        )}
                      </p>

                      <div className="candidate-card__controls">
                        <label className="field candidate-field">
                          <span className="field__label">Start (s)</span>
                          <input
                            className="field__input"
                            data-testid="candidate-start-input"
                            onChange={(event) => {
                              const value = event.target.value;
                              setCandidateRanges((current) => ({
                                ...current,
                                [key]: { ...(current[key] ?? range), start: value },
                              }));
                            }}
                            step="0.001"
                            type="number"
                            value={range.start}
                          />
                        </label>

                        <label className="field candidate-field">
                          <span className="field__label">End (s)</span>
                          <input
                            className="field__input"
                            data-testid="candidate-end-input"
                            onChange={(event) => {
                              const value = event.target.value;
                              setCandidateRanges((current) => ({
                                ...current,
                                [key]: { ...(current[key] ?? range), end: value },
                              }));
                            }}
                            step="0.001"
                            type="number"
                            value={range.end}
                          />
                        </label>
                      </div>
                    </div>

                    <button
                      className="primary-button"
                      data-testid="candidate-confirm-button"
                      disabled={candidate.candidate_id === undefined || exportClipMutation.isPending}
                      onClick={() => {
                        void exportClipMutation.mutateAsync(candidate);
                      }}
                      type="button"
                    >
                      {exportClipMutation.isPending ? "Exporting clip..." : "Confirm export"}
                    </button>
                  </li>
                );
              })}
            </ol>
          ) : zeroCandidateMessage ? (
            <div className="workspace-empty-state">
              <p className="eyebrow">Zero-candidate state</p>
              <h4>No highlight candidates available</h4>
              <p>{zeroCandidateMessage}</p>
            </div>
          ) : (
            <p className="support-copy">Highlight candidate details appear here once the ranked JSON artifact is available.</p>
          )}

          {exportClipMutation.isError ? (
            <p className="form-error">{exportClipMutation.error instanceof Error ? exportClipMutation.error.message : "Clip export failed."}</p>
          ) : null}
        </section>
      </div>

      <section className="workspace-section">
        <div className="workspace-section__header">
          <div>
            <p className="eyebrow">Downloads</p>
            <h4>Artifact downloads</h4>
          </div>
        </div>

        {downloadArtifacts.length > 0 ? (
          <div className="workspace-downloads">
            {downloadArtifacts.map((artifact) => (
              <a className="download-link" download href={resolveArtifactUrl(artifact.path)} key={artifact.id}>
                {getDownloadLabel(artifact.kind)}
              </a>
            ))}
          </div>
        ) : (
          <p className="support-copy">Download actions appear here as subtitle, report, and clip artifacts are persisted.</p>
        )}
      </section>

      <section className="workspace-section">
        <div className="workspace-section__header">
          <div>
            <p className="eyebrow">Exported clips</p>
            <h4>Downloadable MP4 artifacts</h4>
          </div>
        </div>

        {exportedClipArtifacts.length > 0 ? (
          <div className="artifact-list">
            {exportedClipArtifacts.map((artifact) => (
              <article className="artifact-card" key={artifact.id}>
                <div className="artifact-card__header">
                  <strong>{artifact.filename}</strong>
                  <span className="status-badge status-badge--success">Clip export</span>
                </div>
                <p className="artifact-card__path">{formatTimestamp(artifact.start_s, artifact.end_s)}</p>
                <p className="support-copy">{`Candidate ${artifact.candidate_id}`}</p>
                <a className="download-link" download href={resolveArtifactUrl(artifact.path)}>
                  Download exported clip
                </a>
              </article>
            ))}
          </div>
        ) : (
          <p className="support-copy">Confirmed clip exports show up here as downloadable MP4 artifacts.</p>
        )}
      </section>
    </section>
  );
}
