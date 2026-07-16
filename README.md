# Nyaru-Clipper

当前项目仍处于测试阶段，基于 OMO Agent 工作流，由 GPT-5.4 全程构建。

项目文档与手册已整理在 `docs/` 目录下，欢迎继续改进与完善。

一个面向局域网单机环境的 Bilibili 录播处理工作台，用于下载已结束录播、生成字幕、完成中日双语翻译、提出热点候选片段，并在 WebUI 中人工确认后导出切片。

## 当前范围

- 仅面向**已结束 VOD**，不包含直播录制与自动发布
- 仅面向**可信内网 / 单机 GPU** 场景
- 当前仍是 **MVP / 测试阶段**

优先阅读以下文档：

- `docs/deployment-guide.md`：English deployment guide, recommends `uv + pnpm` as the primary local and self-hosted workflow
- `docs/deployment-guide.zh-CN.md`：中文部署指南，明确 `uv + pnpm` 为主路径，Docker 仅作为回退方案
- `docs/operator-manual.md`：English operator manual
- `docs/operator-manual.zh-CN.md`：中文运维手册
- `docs/README.md`：English documentation index
- `docs/README.zh-CN.md`：中文文档索引

## 主要依赖的开源组件

本项目自身代码采用 **GNU General Public License v3.0 only（GPL-3.0-only）**，但功能实现依赖多个第三方开源项目 / 工具。使用、分发或二次部署时，请同时遵守 GPL-3.0-only 与它们各自的许可证、服务条款及使用限制。

目前仓库中已明确使用或安装的主要组件包括：

- 后端：FastAPI、Uvicorn、SQLModel、Transformers、PyTorch、WhisperX、PySceneDetect
- 前端：React、React Router、TanStack Query、Vite、Playwright
- 运行工具：BBDown、yt-dlp、ffmpeg、ffprobe

上述信息可在以下文件中直接看到：

- `backend/pyproject.toml`
- `web/package.json`
- `infra/docker/api.Dockerfile`

## 合规与版权说明

为避免版权与许可证纠纷，请特别注意：

1. **本仓库的 GPL-3.0-only 协议只覆盖本项目自身源码**，不自动覆盖第三方依赖、模型权重、下载工具或媒体内容。
2. **Bilibili 视频内容、字幕、封面、直播切片等版权归原作者或权利人所有**。请在合法授权范围内使用。
3. `BBDown`、`yt-dlp`、`ffmpeg`、`WhisperX`、`Transformers`、`PyTorch` 等组件均有各自许可证与使用要求，发布前请自行核对。
4. 如果你要对外分发镜像、部署服务、公开演示、商用或再授权，建议额外准备：
   - 第三方许可证清单
   - 模型与工具来源说明
   - 内容使用授权证明
   - 必要的免责声明与合规审查

## 使用边界

根据当前 `docs/operator-manual.md` 的说明，本项目**不适合直接公开部署到互联网**。当前没有完整的：

- 用户认证
- TLS 终止
- 速率限制
- 多用户隔离
- 完整密钥管理

如果你准备继续开源发布，建议下一步补充 `NOTICE` / `THIRD_PARTY_LICENSES` 文档，集中列出第三方组件及其许可证。
