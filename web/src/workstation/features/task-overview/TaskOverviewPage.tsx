import { CircleCheck, CirclePause, CircleX, LoaderCircle, RotateCw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import type { ArtifactReadinessRecord, ArtifactRecord } from "../../../lib/types";
import { ExistingReviewWorkspace } from "./ExistingReviewWorkspace";
import { getWorkstationTaskOverview } from "./api";
import { RecoveryPanel } from "./RecoveryPanel";
import { StageRail } from "./StageRail";
import { workstationKeys } from "../../api/queryKeys";

interface TaskOverviewPageProps {
  readonly taskId: string;
}

interface TitleSegmenter {
  segment(input: string): Iterable<{ readonly segment: string }>;
}

interface TitleSegmenterConstructor {
  new (locales: string, options: { readonly granularity: "word" }): TitleSegmenter;
}

const titleCjkCharacter = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;
const japaneseCharacter = /[\p{Script=Hiragana}\p{Script=Katakana}]/u;
const titleContentToken = /[\p{L}\p{N}]/u;
const titlePostposition = /^(?:的|地|得|中|中的|里|上|下|内|外|前|后|间|时|の|に|へ|を|が|は|も|と|で|や|か|ね|よ|から|まで|より|など|だけ|ほど|くらい|ので|のに|には|では|とは|にも|의|은|는|이|가|을|를|에|에서|로|으로|와|과|도|만|까지|부터)$/u;
const japaneseParticle = /^(?:の|に|へ|を|が|は|も|と|で|や|か|ね|よ|から|まで|より|など|だけ|ほど|くらい|ので|のに|には|では|とは|にも)$/u;
const japanesePredicateContinuation = /^(?:する|した|して|される|された|されて|ある|いる|なる|なった|できる|できた|ない|たい)$/u;
const titlePhraseLengthLimit = 12;

function isTitleSegmenterConstructor(value: unknown): value is TitleSegmenterConstructor {
  return typeof value === "function";
}

function groupedJapaneseTitlePhrases(segments: readonly string[]): string[] {
  const phrases: string[] = [];
  let phrase = "";
  let phraseEndsWithPredicate = false;
  function flushPhrase(): void {
    if (phrase === "") return;
    phrases.push(phrase);
    phrase = "";
    phraseEndsWithPredicate = false;
  }

  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index];
    if (!titleContentToken.test(segment)) {
      flushPhrase();
      phrases.push(segment);
      continue;
    }

    const nextSegment = segments[index + 1];
    let unit = segment;
    let unitEndsWithPredicate = japanesePredicateContinuation.test(segment);
    if (japaneseParticle.test(segment)) {
      if (nextSegment === undefined || !titleContentToken.test(nextSegment)) {
        flushPhrase();
        phrases.push(segment);
        continue;
      }
      unit = `${segment}${nextSegment}`;
      unitEndsWithPredicate = japanesePredicateContinuation.test(nextSegment);
      index += 1;
      const predicateSegment = segments[index + 1];
      if (predicateSegment !== undefined && japanesePredicateContinuation.test(predicateSegment)) {
        unit = `${unit}${predicateSegment}`;
        unitEndsWithPredicate = true;
        index += 1;
      }
    } else if (nextSegment !== undefined && japanesePredicateContinuation.test(nextSegment)) {
      unit = `${segment}${nextSegment}`;
      unitEndsWithPredicate = true;
      index += 1;
    }

    if (phrase === "" || (!phraseEndsWithPredicate && phrase.length + unit.length <= titlePhraseLengthLimit)) {
      phrase = `${phrase}${unit}`;
      phraseEndsWithPredicate = unitEndsWithPredicate;
      continue;
    }
    flushPhrase();
    phrase = unit;
    phraseEndsWithPredicate = unitEndsWithPredicate;
  }
  flushPhrase();
  return phrases;
}

function groupedTitlePhrases(segments: readonly string[]): string[] {
  return segments.reduce<string[]>((currentPhrases, segment) => {
    const previousPhrase = currentPhrases[currentPhrases.length - 1];
    const combinedLength = previousPhrase === undefined ? 0 : previousPhrase.length + segment.length;
    if (previousPhrase !== undefined && combinedLength <= titlePhraseLengthLimit && titleCjkCharacter.test(previousPhrase) && titlePostposition.test(segment)) {
      currentPhrases[currentPhrases.length - 1] = `${previousPhrase}${segment}`;
      return currentPhrases;
    }
    currentPhrases.push(segment);
    return currentPhrases;
  }, []);
}

function segmentedTaskTitle(title: string): ReactNode {
  if (typeof Intl === "undefined") return title;
  const segmenterConstructor: unknown = Reflect.get(Intl, "Segmenter");
  if (!isTitleSegmenterConstructor(segmenterConstructor)) return title;

  const segments = Array.from(new segmenterConstructor("zh-CN", { granularity: "word" }).segment(title), ({ segment }) => segment);
  const phrases = japaneseCharacter.test(title) ? groupedJapaneseTitlePhrases(segments) : groupedTitlePhrases(segments);

  return phrases.map((phrase, index) => titleCjkCharacter.test(phrase) && phrase.length <= titlePhraseLengthLimit && !japaneseParticle.test(phrase)
    ? <span className="ny-task-overview__title-phrase" key={`${index}-${phrase}`}>{phrase}</span>
    : phrase);
}

function overviewArtifacts(task: Awaited<ReturnType<typeof getWorkstationTaskOverview>>): ArtifactRecord[] {
  return task.artifacts.map((artifact) => ({
    id: artifact.artifact_id,
    kind: artifact.kind,
    metadata_json: artifact.metadata_json,
    path: artifact.path,
    stage_name: artifact.stage_name,
    task_id: task.task_id,
  }));
}

function overviewReadiness(task: Awaited<ReturnType<typeof getWorkstationTaskOverview>>): ArtifactReadinessRecord[] {
  return task.artifact_readiness.map((artifact) => ({
    artifact_id: artifact.artifact_id,
    kind: artifact.kind,
    path: artifact.path,
    stage_name: artifact.stage_name,
    status: artifact.status,
  }));
}

function taskStatusCopy(status: string): { readonly label: string; readonly tone: "failed" | "running" | "success" | "warning" } {
  switch (status) {
    case "pending": return { label: "等待开始", tone: "warning" };
    case "running": return { label: "正在处理", tone: "running" };
    case "success": return { label: "任务已完成", tone: "success" };
    case "cancelled": return { label: "任务已取消", tone: "warning" };
    case "failed": return { label: "任务需要恢复", tone: "failed" };
    default: return { label: status, tone: "warning" };
  }
}

function StatusIcon({ tone }: { readonly tone: "failed" | "running" | "success" | "warning" }): ReactNode {
  switch (tone) {
    case "failed": return <CircleX aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
    case "running": return <LoaderCircle aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
    case "success": return <CircleCheck aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
    case "warning": return <CirclePause aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />;
  }
}

export function TaskOverviewPage({ taskId }: TaskOverviewPageProps): ReactNode {
  const [searchParams, setSearchParams] = useSearchParams();
  const overviewQuery = useQuery({ queryKey: workstationKeys.detail(taskId), queryFn: () => getWorkstationTaskOverview(taskId) });

  if (overviewQuery.isPending) {
    return <section className="ny-workstation-page"><p className="ny-workstation__eyebrow">任务概览</p><h1 className="ny-workstation-page__title">正在读取任务概览</h1><p className="ny-feedback ny-feedback--loading">正在获取阶段、产物与安全日志。</p></section>;
  }
  if (overviewQuery.isError || overviewQuery.data === undefined) {
    return <section className="ny-workstation-page"><p className="ny-workstation__eyebrow">任务概览</p><h1 className="ny-workstation-page__title">任务概览无法读取</h1><button className="ny-button" onClick={() => void overviewQuery.refetch()} type="button"><RotateCw aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />重新读取任务概览</button></section>;
  }

  const task = overviewQuery.data;
  const status = taskStatusCopy(task.status);
  const selectedStage = searchParams.get("stage") ?? task.current_stage;
  function selectStage(stageName: string): void {
    const nextSearchParams = new URLSearchParams(searchParams);
    nextSearchParams.set("stage", stageName);
    setSearchParams(nextSearchParams, { replace: true });
  }
  return (
    <section className="ny-task-overview" aria-labelledby="task-overview-title">
      <header className="ny-task-overview__header">
        <div>
          <p className="ny-workstation__eyebrow">任务概览</p>
          <h1 aria-label={task.title} className="ny-task-overview__title ny-workstation-page__title" id="task-overview-title">{segmentedTaskTitle(task.title)}</h1>
          <p className="ny-workstation-page__copy">{task.source_label}</p>
        </div>
        <p className={`ny-stamp ny-stamp--${status.tone}`}><StatusIcon tone={status.tone} />{status.label}</p>
      </header>
      <StageRail executionProgress={task.execution_progress} onSelectStage={selectStage} selectedStage={selectedStage} stages={task.stages} />
      <RecoveryPanel actions={task.recovery_actions} taskId={task.task_id} />
      <ExistingReviewWorkspace artifactReadiness={overviewReadiness(task)} artifacts={overviewArtifacts(task)} taskId={task.task_id} />
    </section>
  );
}
