# 运维手册

## 适用范围

这套系统是一个面向**受信任局域网**的 MVP，假设只有一台 GPU 主机和一个活动 worker。

它面向以下场景：

- 一次只处理一个已结束的 Bilibili VOD
- 一个基于 SQLite 的持久化单 worker 循环
- 一个受信任的操作人员
- 所有本地存储都落在仓库下的 `data/` 目录树中

它不适合公网部署、多用户访问或互联网暴露认证入口。

## 服务结构

无论你使用主路径还是 Docker 回退路径，项目暴露的都是同一组运行角色：

- `api`：在 `8000` 端口运行 FastAPI
- `worker`：运行 `app.worker` 中的持久化单 worker 循环
- `web`：在 `5173` 端口运行 Vite 开发服务器

主路径通过仓库脚本启动这些角色。Docker 只作为回退路径保留。

## 存储与挂载

当前 Compose 使用如下 bind mount：

- `../data:/data`
- `../data/model-cache:/models`

其中保存的内容：

- `/data/tasks.sqlite3`：任务元数据和队列状态
- `/data/tasks/<task_id>/...`：原始媒体、工作文件、报告、导出文件和日志
- `/models/whisperx`：WhisperX 缓存目录
- `/models/hf`：Hugging Face / Transformers 缓存目录

单任务目录结构：

- `/data/tasks/<task_id>/raw`
- `/data/tasks/<task_id>/work`
- `/data/tasks/<task_id>/exports`
- `/data/tasks/<task_id>/reports`
- `/data/tasks/<task_id>/logs`

## 启动方式

优先使用 `uv + pnpm`。Docker 仅作为回退方案。

首次部署前请先阅读 `docs/deployment-guide.zh-CN.md`。其中已经覆盖 Linux 加 CUDA、WSL 加 ROCm、pip 兼容路径、运行时能力检查和 Docker 回退说明。

### 主路径启动

在仓库根目录执行：

```bash
./scripts/install_backend_linux_cuda.sh
pnpm --dir web install --frozen-lockfile
./scripts/dev_up.sh
```

上面这条专用后端安装包装脚本就是 Linux + CUDA 主机路径的受支持安装合同，对应仓库中检查通过的 Linux CUDA 依赖配置。

如果你运行的是 WSL2 Ubuntu 22.04 或 24.04，并且按 AMD 官方路径部署了 ROCm，请改用：

```bash
./scripts/install_backend_wsl_rocm.sh
pnpm --dir web install --frozen-lockfile
./scripts/check_wsl_rocm.sh
./scripts/dev_up.sh
```

WSL 运行时启动仍然继续复用 `./scripts/dev_api.sh`、`./scripts/dev_worker.sh`、`./scripts/dev_web.sh`、`./scripts/dev_up.sh` 这组共用入口。

### 分进程启动

在仓库根目录执行：

```bash
./scripts/dev_api.sh
./scripts/dev_worker.sh
./scripts/dev_web.sh
```

### Docker 回退启动

只有在主机侧 `uv + pnpm` 流程不方便时才使用：

```bash
docker compose -f infra/docker-compose.yml up -d --build api worker web
```

`infra/docker-compose.yml` 依然提供同一组 `api`、`worker`、`web` 服务。

常用覆盖环境变量：

- `APP_HOST`：修改 API 绑定地址，默认 `0.0.0.0`
- `APP_PORT`：修改 API 端口，默认 `8000`
- `VITE_HOST`：修改 Web 绑定地址，默认 `0.0.0.0`
- `VITE_PORT`：修改 Web 端口，默认 `5173`
- `VITE_API_BASE_URL`：让浏览器访问正确的主机 API 地址
- `APP_BILIBILI_COOKIE_PATH`：指定 Bilibili Cookie 文件路径
- `APP_DATA_DIR`：把数据目录放到仓库 `data/` 之外时使用

### Web UI 的局域网访问说明

默认 `VITE_API_BASE_URL` 为 `http://127.0.0.1:8000/api`。

当浏览器和服务运行在同一台机器上时，这样配置是可行的。如果使用者从局域网其他设备打开 UI，请在启动前把 `VITE_API_BASE_URL` 改成主机的局域网地址，例如：

```bash
VITE_API_BASE_URL=http://192.168.1.50:8000/api ./scripts/dev_web.sh
```

如果你走 Docker 回退路径，也要在 `docker compose up` 前设置同样的值。

## Bilibili Cookie 与访问限制说明

下载层通过 `APP_BILIBILI_COOKIE_PATH` 支持 Cookie 访问。

重要说明：

- 一些公开 VOD 在没有 Cookie 时也可能能下载。
- 私有、会员限定或区域受限 VOD 在没有有效 Cookie 文件时可能失败。
- 后端接受的是**文件路径**，不是直接粘贴的 Cookie 字符串。
- `BBDown` 读取 Cookie 内容，而 `yt-dlp` 回退路径读取 Cookie 文件路径，因此该文件必须在容器内可读。

当前 Compose 默认**不会**自动挂载 Cookie 文件。如果需要，请手动挂载，并把 `APP_BILIBILI_COOKIE_PATH` 指向容器内对应路径。

## 模型准备说明

后端采用本地优先策略。

当前 `backend/app/settings.py` 的默认值为：

- WhisperX 模型：`large-v3`
- WhisperX 设备：`cuda`
- WhisperX 计算类型：`float16`
- 翻译模型：`facebook/nllb-200-distilled-600M`
- 翻译设备：`cuda`

运行预期：

- 第一次执行 ASR 或翻译时，可能会向 `/models` 填充模型缓存。
- 冷启动下载模型可能较慢。
- 在正式使用前预热模型缓存更稳妥。
- CPU 回退不是目标工作模式，只应视为性能明显下降的降级方案。

## GPU 假设

当前 MVP 假设只有一台 GPU 主机和一个活动 worker。

支持的主机侧运行目标只有两类：

- Linux + CUDA
- WSL2 Ubuntu 22.04 或 24.04，加官方 AMD ROCm 路径，并且运行时能够报告 `wsl-rocm`

Docker 回退路径目前仍然是 NVIDIA 导向的。`infra/docker-compose.yml` 依然设置了：

- `NVIDIA_VISIBLE_DEVICES`
- `NVIDIA_DRIVER_CAPABILITIES`
- `api` 与 `worker` 的 GPU 预留配置

不要把 Docker 回退路径当作 WSL ROCm 路径。

整个流水线按设计只允许单 worker 运行。不要在当前 MVP 中横向扩容 `worker`。

## 后端镜像中的媒体工具

`api` 和 `worker` 共用的后端镜像当前会在构建阶段直接安装这些运行时工具：

- `BBDown`
- `yt-dlp`
- `ffmpeg`
- `ffprobe`

容器内会把 `/app/.bin` 置于 `PATH` 前面，因此后端仍可继续使用 `backend/app/settings.py` 中的默认命令名，而实际会解析到镜像中安装好的工具。

注意：镜像**不会**预下载 WhisperX 或翻译模型权重。模型缓存仍然会在首次运行或手动预热时写入 `/models`。

## 运行流程

worker 会一次领取一个待处理的持久化任务。

标准阶段顺序如下：

1. `ingest`
2. `media_prep`
3. `asr`
4. `translation`
5. `highlight`
6. `export`
7. `report`

在当前 MVP 中，流水线内的 `export` 阶段会先被标记为 `skipped`，直到用户通过 `POST /api/tasks/{task_id}/clips` 确认导出某个切片。

## 运行时能力可见性

运行时能力检查是非阻塞的可见性信号。

操作人员应重点看四个位置：

- `./scripts/check_wsl_rocm.sh`，这是 WSL 专用的严格 doctor，自检通过前不要信任 WSL 主机
- `/api/health`，用于就绪检查，同时包含精简后的 `runtime_capabilities`
- `/api/runtime/capabilities`，用于查看完整载荷，包含 `status`、`detected_profile`、`platform`、`accelerator`、`dependencies`、`warnings`、`issues`
- 启动日志和 worker 日志，其中会出现 `runtime_capabilities_startup` 与 `worker_preflight_runtime=<json>`

warning 不会阻止启动，但会持续暴露在 API、UI 和日志中，方便在执行关键任务前修复降级环境。

### 精简摘要里应该看到什么

`/api/health` 仍然保持精简，但运维侧应该能直接看到：

- `runtime_capabilities.status`
- `runtime_capabilities.detected_profile`
- `runtime_capabilities.warnings`
- `runtime_capabilities.issue_codes`
- `runtime_capabilities.accelerator`

其中 `accelerator` 的精简摘要足够确认 `torch_build_family`、`available`、`device_count`、`device_name` 是否合理，无需先打开完整载荷。

### WSL mismatch code 的运维含义

如果目标主机是 WSL + ROCm，这三个 issue code 就是面向操作人员的 mismatch 合同：

- `wrong_torch_build_cuda_on_wsl`：已经识别到 WSL，但后端环境里还是 CUDA 版 torch。重新执行 `./scripts/install_backend_wsl_rocm.sh`，然后重新跑 `./scripts/check_wsl_rocm.sh`。
- `cpu_only_torch_on_wsl`：已经识别到 WSL，但后端环境里是 CPU-only torch。重新执行 `./scripts/install_backend_wsl_rocm.sh`，然后重新跑 `./scripts/check_wsl_rocm.sh`。
- `hip_build_no_device`：已经装了 ROCm torch，但 `torch.cuda` 仍然看不到 GPU。先修复 WSL ROCm 栈，再重新跑 `./scripts/check_wsl_rocm.sh`。

这些代码应该在 API、UI 环境状态卡片、API 启动日志和 worker 预检日志中保持一致。

## 日志与排障

每个任务的阶段日志位于 `/data/tasks/<task_id>/logs/<stage>.log`。

任务失败时建议按以下顺序排查：

1. 先在 UI 或 `/api/tasks/<task_id>/stages` 中确认失败阶段
2. 打开对应的 `/data/tasks/<task_id>/logs/<stage>.log`
3. 检查模型缓存是否已下载且具有可读权限
4. 如果 Bilibili 访问失败，检查 Cookie 是否可用
5. 检查当前运行环境里的媒体工具是否可解析

主路径示例：

```bash
python3 -c "import shutil; print({name: shutil.which(name) for name in ('BBDown', 'yt-dlp', 'ffmpeg', 'ffprobe')})"
```

Docker 回退示例：

```bash
docker compose -f infra/docker-compose.yml exec api python -c "import shutil; print({name: shutil.which(name) for name in ('BBDown', 'yt-dlp', 'ffmpeg', 'ffprobe')})"
```

## 仅限局域网，不支持公网部署

当前 MVP 只假设在受信任局域网中运行。

不要把它视为可直接公网暴露的系统。它目前**没有**：

- 身份认证
- TLS 终止
- 限流
- 反向代理加固
- 专门的密钥管理层
- 多用户隔离

不要把 `5173` 或 `8000` 端口直接暴露到公网。
