import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, ExternalLink, FileVideo2, Plus, X } from "lucide-react";
import { useReducer, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ReactNode } from "react";

import { BilibiliSourceStep } from "./BilibiliSourceStep";
import { LocalSourceStep } from "./LocalSourceStep";
import { TaskOptionsStep } from "./TaskOptionsStep";
import { TaskCreateApiError, createWorkstationTask, getProcessingProfiles, inspectBilibiliSource } from "./api";
import type { LocalFileSelection } from "./LocalSourceStep";
import type { BilibiliInspection, CreateTaskRequest } from "./api";
import { workstationKeys } from "../../api/queryKeys";

type SourceKind = "bilibili" | "local";
type ImportMode = "copy" | "reference";
type FieldErrors = Readonly<Partial<Record<"priority" | "profile_id" | "source", string>>>;

interface BilibiliDraft {
  readonly kind: "bilibili";
  readonly url: string;
}

interface LocalDraft {
  readonly importMode: ImportMode;
  readonly kind: "local";
  readonly name: string;
  readonly relativePath: string;
  readonly rootId: string;
}

type DraftSource = BilibiliDraft | LocalDraft;
type ValidatedSource =
  | { readonly inspection: BilibiliInspection; readonly kind: "bilibili"; readonly url: string }
  | LocalDraft;

type CreateTaskState =
  | { readonly bilibiliUrl: string; readonly errors: FieldErrors; readonly sourceKind: SourceKind | null; readonly step: "source" }
  | { readonly errors: FieldErrors; readonly inspection: BilibiliInspection | null; readonly source: DraftSource; readonly step: "inspect" }
  | { readonly errors: FieldErrors; readonly priority: number; readonly profileId: string; readonly source: ValidatedSource; readonly step: "options" }
  | { readonly priority: number; readonly profileId: string; readonly request: CreateTaskRequest; readonly source: ValidatedSource; readonly step: "submitting" };

type CreateTaskAction =
  | { readonly kind: "select-source"; readonly sourceKind: SourceKind }
  | { readonly kind: "set-bilibili-url"; readonly url: string }
  | { readonly kind: "set-inspected-source"; readonly inspection: BilibiliInspection; readonly source: BilibiliDraft }
  | { readonly kind: "set-local-source"; readonly source: LocalDraft }
  | { readonly importMode: ImportMode; readonly kind: "set-import-mode" }
  | { readonly kind: "open-options" }
  | { readonly kind: "set-options"; readonly priority?: number; readonly profileId?: string }
  | { readonly kind: "set-submit"; readonly request: CreateTaskRequest }
  | { readonly errors: FieldErrors; readonly kind: "submission-failed" }
  | { readonly kind: "set-source-error"; readonly message: string }
  | { readonly kind: "back-to-source" };

const initialState: CreateTaskState = { bilibiliUrl: "", errors: {}, sourceKind: null, step: "source" };

function createTaskReducer(state: CreateTaskState, action: CreateTaskAction): CreateTaskState {
  switch (action.kind) {
    case "select-source":
      return { bilibiliUrl: "", errors: {}, sourceKind: action.sourceKind, step: "source" };
    case "set-bilibili-url":
      return state.step === "source" ? { ...state, bilibiliUrl: action.url, errors: {} } : state;
    case "set-inspected-source":
      return { errors: {}, inspection: action.inspection, source: action.source, step: "inspect" };
    case "set-local-source":
      return { errors: {}, inspection: null, source: action.source, step: "inspect" };
    case "set-import-mode":
      return state.step === "inspect" && state.source.kind === "local" ? { ...state, source: { ...state.source, importMode: action.importMode } } : state;
    case "open-options": {
      if (state.step !== "inspect") return state;
      let source: ValidatedSource;
      if (state.source.kind === "bilibili") {
        const inspection = state.inspection;
        if (inspection === null) return state;
        source = { inspection, kind: "bilibili", url: inspection.normalized_url };
      } else {
        source = state.source;
      }
      return {
        errors: {},
        priority: 0,
        profileId: "standard",
        source,
        step: "options",
      };
    }
    case "set-options":
      return state.step === "options" ? { ...state, errors: {}, priority: action.priority ?? state.priority, profileId: action.profileId ?? state.profileId } : state;
    case "set-submit":
      return state.step === "options" ? { priority: state.priority, profileId: state.profileId, request: action.request, source: state.source, step: "submitting" } : state;
    case "submission-failed":
      return state.step === "submitting" ? { errors: action.errors, priority: state.priority, profileId: state.profileId, source: state.source, step: "options" } : state;
    case "set-source-error":
      return state.step === "source" ? { ...state, errors: { source: action.message } } : state;
    case "back-to-source":
      return initialState;
    default:
      return state;
  }
}

function isBilibiliUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" && (parsed.hostname === "www.bilibili.com" || parsed.hostname === "bilibili.com" || parsed.hostname === "b23.tv");
  } catch {
    return false;
  }
}

function requestFor(source: ValidatedSource, profileId: string, priority: number): CreateTaskRequest | null {
  if (profileId !== "standard") return null;
  if (source.kind === "bilibili") return { priority, profile_id: "standard", source: { kind: "bilibili", url: source.url } };
  return { priority, profile_id: "standard", source: { import_mode: source.importMode, kind: "local", relative_path: source.relativePath, root_id: source.rootId } };
}

function messageFor(error: unknown): string {
  return error instanceof TaskCreateApiError ? error.action : "任务没有创建，请重试。";
}

function Preview({ source, inspection }: { readonly inspection: BilibiliInspection | null; readonly source: DraftSource }): ReactNode {
  if (source.kind === "local") return <section className="ny-task-create__preview" aria-label="已选本地来源"><p className="ny-workstation__eyebrow">本地文件</p><h3>{source.name}</h3><p>仅保存受信任目录中的相对位置；请选择后续使用原文件或复制。</p></section>;
  if (inspection === null) return null;
  return <section className="ny-task-create__preview" aria-label="Bilibili 来源预览"><p className="ny-workstation__eyebrow">检查完成</p><h3>{inspection.title ?? inspection.source_video_id}</h3><p>{inspection.uploader ?? "未提供上传者"} · {inspection.duration_seconds === null ? "时长待确认" : `${Math.round(inspection.duration_seconds)} 秒`}</p><p className="ny-task-create__technical">{inspection.normalized_url}</p></section>;
}

interface NewTaskDrawerProps {
  readonly onOpenChange: (open: boolean) => void;
  readonly open: boolean;
}

export function NewTaskDrawer({ onOpenChange, open }: NewTaskDrawerProps): ReactNode {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(createTaskReducer, initialState);
  const [discardOpen, setDiscardOpen] = useState(false);
  const inspectionMutation = useMutation({ mutationFn: inspectBilibiliSource, onError: (error) => dispatch({ kind: "set-source-error", message: messageFor(error) }), onSuccess: (inspection, url) => dispatch({ inspection, kind: "set-inspected-source", source: { kind: "bilibili", url } }) });
  const profilesQuery = useQuery({ enabled: state.step === "options" || state.step === "submitting", queryKey: ["workstation", "processing-profiles"], queryFn: getProcessingProfiles });
  const createMutation = useMutation({
    mutationFn: createWorkstationTask,
    onError: (error) => dispatch({ errors: error instanceof TaskCreateApiError ? error.fieldErrors : {}, kind: "submission-failed" }),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: workstationKeys.summary });
      await queryClient.invalidateQueries({ queryKey: workstationKeys.queue });
      await queryClient.invalidateQueries({ queryKey: workstationKeys.all });
      onOpenChange(false);
      navigate(`/workstation/tasks/${result.task_id}`);
    },
  });
  const dirty = state.step !== "source" || state.sourceKind !== null;

  function requestClose(): void {
    if (dirty) setDiscardOpen(true);
    else onOpenChange(false);
  }

  function inspectSource(): void {
    if (state.step !== "source") return;
    const url = state.bilibiliUrl.trim();
    if (!isBilibiliUrl(url)) {
      dispatch({ kind: "set-source-error", message: "请输入有效的 Bilibili 链接。" });
      return;
    }
    inspectionMutation.mutate(url);
  }

  function chooseLocalSource(selection: LocalFileSelection): void {
    dispatch({ kind: "set-local-source", source: { importMode: "reference", kind: "local", name: selection.name, relativePath: selection.relativePath, rootId: selection.rootId } });
  }

  function submit(): void {
    if (state.step !== "options") return;
    const request = requestFor(state.source, state.profileId, state.priority);
    if (request === null) {
      dispatch({ kind: "submission-failed", errors: { profile_id: "当前工作站只支持 Standard 处理配置。" } });
      return;
    }
    dispatch({ kind: "set-submit", request });
    createMutation.mutate(request);
  }

  const localImportMode = state.step === "inspect" && state.source.kind === "local" ? state.source.importMode : null;
  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen) requestClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="ny-dialog-overlay" />
        <Dialog.Content className="ny-overlay ny-drawer ny-task-create" aria-describedby="task-create-description">
          <header className="ny-task-create__header"><div><p className="ny-workstation__eyebrow">队列输入</p><Dialog.Title className="ny-overlay__title">新建任务</Dialog.Title></div><button aria-label="关闭新建任务" className="ny-button ny-button--quiet" onClick={requestClose} type="button"><X aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" /></button></header>
          <Dialog.Description className="ny-overlay__description" id="task-create-description">先核验来源，再用标准处理配置把任务放入单 GPU 队列。</Dialog.Description>
          {state.step === "source" ? <section className="ny-task-create__step"><div className="ny-task-create__source-switch"><button aria-pressed={state.sourceKind === "bilibili"} className="ny-button" onClick={() => dispatch({ kind: "select-source", sourceKind: "bilibili" })} type="button"><ExternalLink aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />Bilibili 录播</button><button aria-pressed={state.sourceKind === "local"} className="ny-button" onClick={() => dispatch({ kind: "select-source", sourceKind: "local" })} type="button"><FileVideo2 aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />本地文件</button></div>{state.sourceKind === "bilibili" ? <BilibiliSourceStep error={state.errors.source} isInspecting={inspectionMutation.isPending} onInspect={inspectSource} onUrlChange={(url) => dispatch({ kind: "set-bilibili-url", url })} url={state.bilibiliUrl} /> : null}{state.sourceKind === "local" ? <LocalSourceStep onSelect={chooseLocalSource} /> : null}</section> : null}
          {state.step === "inspect" ? <section className="ny-task-create__step"><Preview inspection={state.inspection} source={state.source} />{state.source.kind === "local" ? <div className="ny-task-create__radio-actions"><button className={`ny-button${localImportMode === "reference" ? " ny-button--primary" : ""}`} onClick={() => dispatch({ importMode: "reference", kind: "set-import-mode" })} role="radio" aria-checked={localImportMode === "reference"} type="button"><CheckCircle2 aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />引用原始文件</button><button className={`ny-button${localImportMode === "copy" ? " ny-button--primary" : ""}`} onClick={() => dispatch({ importMode: "copy", kind: "set-import-mode" })} role="radio" aria-checked={localImportMode === "copy"} type="button"><Copy aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />复制到任务存储</button></div> : null}<div className="ny-overlay__actions"><button className="ny-button ny-button--quiet" onClick={() => dispatch({ kind: "back-to-source" })} type="button">重新选择</button><button className="ny-button ny-button--primary" onClick={() => dispatch({ kind: "open-options" })} type="button">继续设置</button></div></section> : null}
          {state.step === "options" || state.step === "submitting" ? <section className="ny-task-create__step"><TaskOptionsStep errors={state.step === "options" ? state.errors : {}} onPriorityChange={(priority) => dispatch({ kind: "set-options", priority })} onProfileChange={(profileId) => dispatch({ kind: "set-options", profileId })} priority={state.priority} profileId={state.profileId} profiles={profilesQuery.data ?? []} />{profilesQuery.isError ? <p className="ny-field__message ny-field__message--error">处理配置暂时不可读取；仍会验证默认 Standard 配置。</p> : null}<div className="ny-overlay__actions"><button className="ny-button ny-button--quiet" disabled={state.step === "submitting"} onClick={() => dispatch({ kind: "back-to-source" })} type="button">重新选择来源</button><button className="ny-button ny-button--primary" disabled={state.step === "submitting"} onClick={submit} type="button"><Plus aria-hidden="true" size="var(--ny-icon-default)" strokeWidth="var(--ny-icon-stroke)" />{state.step === "submitting" ? "正在创建任务" : "创建任务"}</button></div></section> : null}
        </Dialog.Content>
      </Dialog.Portal>
      <Dialog.Root open={discardOpen} onOpenChange={setDiscardOpen}><Dialog.Portal><Dialog.Overlay className="ny-dialog-overlay" /><Dialog.Content aria-describedby="task-create-discard-description" className="ny-overlay ny-dialog" role="alertdialog"><Dialog.Title className="ny-overlay__title">放弃未保存的任务设置？</Dialog.Title><Dialog.Description className="ny-overlay__description" id="task-create-discard-description">当前来源和队列设置尚未创建任务。</Dialog.Description><div className="ny-overlay__actions"><button className="ny-button" onClick={() => setDiscardOpen(false)} type="button">继续编辑</button><button className="ny-button ny-button--danger" onClick={() => { setDiscardOpen(false); onOpenChange(false); }} type="button">放弃更改</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    </Dialog.Root>
  );
}
