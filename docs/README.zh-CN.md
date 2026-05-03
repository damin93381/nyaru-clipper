# 文档目录说明

本目录存放项目的操作手册、用户手册、线框图和流程说明。

如果你要先完成部署或本地启动，请优先阅读：

- `deployment-guide.zh-CN.md`：中文部署指南，包含专用 WSL + ROCm 安装、自检、共用运行时入口与 smoke 路径
- `deployment-guide.md`：English deployment guide，包含专用 WSL + ROCm 安装、自检、共用运行时入口与 smoke 路径

当前中文文档对应关系如下：

- `user-manual.zh-CN.md`：用户手册（中文）
- `operator-manual.zh-CN.md`：运维/操作手册（中文）
- `deployment-guide.zh-CN.md`：部署指南（中文）
- `wsl-rocm-investigation.zh-CN.md`：WSL + ROCm 调查记录与结论（中文）
- `wireframes.zh-CN.md`：MVP 页面线框图（中文）
- `processing-flow.zh-CN.md`：处理流程与产物目录说明（中文）

英文原版文档仍保留，便于双语对照和后续维护。如果你的目标环境是 WSL + ROCm，请先看部署指南里的专用路径，再继续阅读运维手册和用户手册。

当前运维手册和部署指南也已经补充了 ASR 生命周期可观测性说明，包括活动 phase 耗时显示、`cancel_requested` 的叠加语义，以及 `force-kill` 的受限可用条件。
