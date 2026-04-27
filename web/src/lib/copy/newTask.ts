import { GLOSSARY_TERMS } from "./glossary";

export type NewTaskProcessingOptionKey = "translation" | "highlight" | "export";

export interface NewTaskProcessingOptionCopy {
  key: NewTaskProcessingOptionKey;
  label: string;
  helpText: string;
  defaultChecked: boolean;
}

export const NEW_TASK_PROCESSING_OPTIONS: readonly NewTaskProcessingOptionCopy[] = [
  {
    key: "translation",
    label: "翻译",
    helpText: "保留双语字幕生成，作为当前工作站可见流程的一部分。",
    defaultChecked: true,
  },
  {
    key: "highlight",
    label: "高光",
    helpText: "即使没有找到可导出片段，也保留高光分析阶段并在界面中展示。",
    defaultChecked: true,
  },
  {
    key: "export",
    label: "导出",
    helpText: "预留片段和报告导出的可见性；片段生成仍需后续人工确认。",
    defaultChecked: true,
  },
] as const;

export const NEW_TASK_COPY = {
  hero: {
    eyebrow: "任务入口",
    title: "将 Bilibili 录播加入标准工作流水线",
    description: "提交一个已结束的录播链接，保留标准阶段可见性，并直接进入后续扩展字幕与高光审阅的详情页。",
  },
  form: {
    eyebrow: GLOSSARY_TERMS.newTask,
    title: "创建任务",
    badge: "单任务 MVP",
    sourceUrlLabel: "Bilibili 录播链接",
    sourceUrlPlaceholder: "https://www.bilibili.com/video/BV1xx411c7mD",
    reservedControlsEyebrow: "预留控制",
    processingOptionsTitle: "可见处理选项",
    processingOptionsDescription: "这些开关为未来的单任务控制预留位置；当前 MVP 后端仍运行标准的阶段化流水线。",
    summary: {
      stagesLabel: "可见阶段",
      navigationLabel: "跳转",
      emptySelection: "未选择任何阶段",
      navigationDescription: "提交成功后会直接跳转到 /tasks/<id>。",
    },
    submitPending: "正在创建任务...",
    submitIdle: "创建任务",
  },
} as const;
