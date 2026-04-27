import { GLOSSARY_TERMS } from "./glossary";

export const APP_SHELL_COPY = {
  header: {
    eyebrow: "单机工作站 MVP",
    title: "Bilibili VTuber 工作台",
    description: "用于提交任务、跟踪处理阶段与后续审核流程的操作界面。",
  },
  navigation: {
    primaryAriaLabel: "主导航",
    newTask: GLOSSARY_TERMS.newTask,
  },
  sideRail: {
    ariaLabel: "环境与未来任务列表区域",
    futureTaskList: {
      eyebrow: "预留区域",
      title: "未来任务列表",
      description: "为历史记录、队列可见性与后续批量/订阅视图预留空间。",
      items: ["当前队列快照", "最近任务历史", "任务筛选与搜索"],
    },
  },
  futureWorkspace: {
    ariaLabel: "未来工作区区域",
    eyebrow: "预留区域",
    title: "未来工作区",
    description: "字幕审阅、高光候选确认与导出能力将在任务 10 中扩展到这一栏。",
    items: ["双语字幕审阅", "高光候选控制", "产物下载快捷入口"],
  },
} as const;
