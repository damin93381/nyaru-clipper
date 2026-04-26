# 部署指南

## 适用范围

本文只覆盖本项目在本地或自托管环境中的部署方式，前提是受信任局域网或单机主机。

推荐把 `uv` 加 `pnpm` 作为主流程。Docker 保留，但只作为回退方案。

本文不扩展到云部署、公网暴露、多用户托管或 CI 编排。

## 推荐路径

| 路径 | 状态 | 适用场景 | 说明 |
| --- | --- | --- | --- |
| Linux + CUDA | 主路径 | Linux GPU 主机上的本地或自托管环境 | 面向完整项目工作流 |
| WSL + ROCm | 支持目标 | 在 WSL 内运行，且运行时能识别 `wsl-rocm` | 目标是完整功能，不是简化模式 |
| pip 兼容路径 | 兼容路径 | 不能直接使用 `uv` 时的后端依赖安装方式 | 只用于兼容，不是首选全栈流程 |
| Docker 回退 | 仅回退 | 主机侧 Python 或 Node 环境不方便时使用 | 不要把 Docker 当作默认路径 |

以下内容不在本文支持范围内：

- 原生 Windows GPU 部署
- 原生 macOS GPU 部署
- 公网暴露

## 共用要求

### 主流程所需工具

- Python `3.11`
- `uv`
- Node.js `>=20`
- `pnpm@10.33.2`，或同一代 pnpm 10 版本
- 主机 `PATH` 上可用的媒体工具：`BBDown`、`yt-dlp`、`ffmpeg`、`ffprobe`

后端依赖的唯一事实来源是 `backend/pyproject.toml`。仓库中的 `backend/requirements.txt` 由 `./scripts/export_backend_requirements.sh` 生成，不应手工修改。

### 共用初始化

在仓库根目录执行：

```bash
uv sync --project backend --frozen
pnpm --dir web install --frozen-lockfile
```

本地脚本会自动创建仓库内的数据与缓存目录。默认值如下：

- `APP_DATA_DIR=./data`
- `APP_MODEL_CACHE_ROOT=./data/model-cache`
- `APP_WHISPERX_MODEL_CACHE_DIR=./data/model-cache/whisperx`
- `HF_HOME=./data/model-cache/hf`
- `TRANSFORMERS_CACHE=./data/model-cache/hf`

## Linux + CUDA 主路径

这是 Linux NVIDIA 主机上的标准本地或自托管部署方式。

### 启动完整栈

```bash
./scripts/dev_up.sh
```

这个脚本会按顺序：

- 用 `./scripts/dev_api.sh` 启动 API
- 等待 `http://127.0.0.1:8000/api/health` 就绪
- 用 `./scripts/dev_worker.sh` 启动 worker
- 用 `./scripts/dev_web.sh` 启动 Web UI

默认本地访问地址：

- API：`http://127.0.0.1:8000`
- Web UI：`http://127.0.0.1:5173`

### 分终端启动

终端 1：

```bash
./scripts/dev_api.sh
```

终端 2：

```bash
./scripts/dev_worker.sh
```

终端 3：

```bash
./scripts/dev_web.sh
```

常用环境变量：

- `APP_HOST` 和 `APP_PORT`，控制 API 绑定地址与端口，默认 `0.0.0.0:8000`
- `VITE_HOST` 和 `VITE_PORT`，控制前端开发服务器，默认 `0.0.0.0:5173`
- `VITE_API_BASE_URL`，默认 `http://127.0.0.1:8000/api`
- `APP_DATA_DIR`，需要把数据目录放到 `./data` 之外时使用
- `APP_BILIBILI_COOKIE_PATH`，下载必须依赖 Cookie 文件时使用

如果浏览器从局域网其他机器访问 Web UI，请在启动前把 `VITE_API_BASE_URL` 改成主机局域网地址，例如：

```bash
VITE_API_BASE_URL=http://192.168.1.50:8000/api ./scripts/dev_web.sh
```

## WSL + ROCm 完整功能目标

当你在 WSL 内运行项目，并且 PyTorch 运行时能识别 ROCm 时，使用这条路径。

这条路径的目标是完整功能，不是降级模式。前提是运行时配置能识别为 `wsl-rocm`，并且所需的主机媒体工具在 WSL 环境内可用。

### 在 WSL 内启动

在 WSL shell 中执行和主路径相同的命令：

```bash
uv sync --project backend --frozen
pnpm --dir web install --frozen-lockfile
./scripts/dev_up.sh
```

如果要分终端运行，也使用同一组脚本：

```bash
./scripts/dev_api.sh
./scripts/dev_worker.sh
./scripts/dev_web.sh
```

### 启动后检查什么

启动后用下面的命令检查运行时画像：

```bash
python3 - <<'PY'
import json
import urllib.request

with urllib.request.urlopen('http://127.0.0.1:8000/api/runtime/capabilities', timeout=5) as response:
    payload = json.loads(response.read().decode('utf-8'))

print(json.dumps(payload, indent=2, ensure_ascii=False))
PY
```

对于正常的 WSL ROCm 环境，返回内容应体现：

- `detected_profile: "wsl-rocm"`
- `accelerator.backend: "rocm"`
- `accelerator.available: true`

如果接口返回 `cpu-only`，启动依然会成功，但说明运行时已经退回 CPU 模式，应先修复 ROCm 路径，再投入实际任务。

## pip 兼容路径

只有在必须兼容纯 `pip` 环境时才使用。首选全栈流程仍然是 `uv` 加 `pnpm`。

### 校验并生成后端 requirements 文件

```bash
./scripts/export_backend_requirements.sh --check
```

如果需要刷新文件：

```bash
./scripts/export_backend_requirements.sh
```

### 用 pip 安装后端依赖

请在仓库根目录使用 Python 3.11：

```bash
python3.11 -m venv .venv-pip
. .venv-pip/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
```

这条路径有几个边界：

- 只把它当作后端兼容安装路径
- 后端依赖的唯一事实来源仍是 `backend/pyproject.toml`
- 不要把它当作完整替代 `uv` 的项目主流程
- 也不要假设它单独就能保证 WSL 加 ROCm 的完整等价能力

如果你在 pip 路径下还需要 Web UI，请单独安装前端依赖：

```bash
pnpm --dir web install --frozen-lockfile
```

## Docker 回退

只有在主机侧 `uv` 加 `pnpm` 流程不方便时才使用 Docker。

### 启动回退栈

```bash
docker compose -f infra/docker-compose.yml up -d --build api worker web
```

停止命令：

```bash
docker compose -f infra/docker-compose.yml down
```

回退栈仍然会提供：

- `8000` 端口上的 API
- `5173` 端口上的 Web UI
- 同样的单 worker 循环

如果浏览器从局域网其他设备访问，请在启动前设置 `VITE_API_BASE_URL`，让浏览器指向主机 API 地址：

```bash
VITE_API_BASE_URL=http://192.168.1.50:8000/api docker compose -f infra/docker-compose.yml up -d --build api worker web
```

Docker 的验证脚本也只应作为回退验证路径：

```bash
./scripts/release_smoke_docker.sh
```

## 能力检查与 warning 语义

运行时能力检查的目标是可见性，不会阻塞启动。

这些信息会出现在以下位置：

- API 就绪接口仍然是 `/api/health`
- `/api/health` 会附带 `runtime_capabilities`，其中只有 `status`、`detected_profile`、`warnings`
- 完整能力信息由 `/api/runtime/capabilities` 提供
- API 启动时会在 `app.runtime` logger 写入一条 `runtime_capabilities_startup` JSON 日志
- 如果存在 warning，worker 阶段日志会追加 `worker_preflight_warning=<json>`
- Web UI 也会显示运行时状态，方便操作人员不看原始日志也能发现问题

完整能力载荷的顶层键为：

- `status`
- `detected_profile`
- `platform`
- `accelerator`
- `dependencies`
- `warnings`

warning 的含义如下：

- 没有检测到 GPU 运行时，会报告 CPU-only warning
- 缺少 `BBDown`、`yt-dlp`、`ffmpeg`、`ffprobe` 等主机工具，会报告 warning
- 缺少可选 diarization 依赖，也会报告 warning
- 这些 warning 会同时暴露在 API、UI 和日志里
- 这些 warning 不会阻止 API 或 worker 启动

如果缺少 `torch`、`transformers`、`whisperx` 这类核心 Python 依赖，能力接口可能返回 `status: "error"`。这个状态依然是观测性的，不会把启动过程变成硬阻塞，但在补齐依赖前，系统并不适合执行真实处理任务。

## 验证命令

主路径验证：

```bash
./scripts/release_smoke_non_docker.sh
```

Docker 回退验证：

```bash
./scripts/release_smoke_docker.sh
```

后端 requirements 产物校验：

```bash
./scripts/export_backend_requirements.sh --check
```

运行时能力快速检查：

```bash
python3 - <<'PY'
import json
import urllib.request

with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5) as response:
    payload = json.loads(response.read().decode('utf-8'))

print(json.dumps(payload, indent=2, ensure_ascii=False))
assert payload['status'] == 'ok'
assert set(payload['runtime_capabilities'].keys()) == {'status', 'detected_profile', 'warnings'}
PY
```

## 排障

### `./scripts/dev_up.sh` 没有把栈成功拉起

先检查主机上是否能找到这些命令：

```bash
python3 - <<'PY'
import json
import shutil

print(json.dumps({
    'uv': shutil.which('uv'),
    'pnpm': shutil.which('pnpm'),
    'python3': shutil.which('python3'),
    'BBDown': shutil.which('BBDown'),
    'yt-dlp': shutil.which('yt-dlp'),
    'ffmpeg': shutil.which('ffmpeg'),
    'ffprobe': shutil.which('ffprobe'),
}, indent=2, ensure_ascii=False))
PY
```

### API 已启动，但能力状态显示 `cpu-only`

- 在 Linux 上，确认 PyTorch 能看到 CUDA 运行时
- 在 WSL 上，确认运行时识别为 `wsl-rocm`
- 在执行真实任务前，先查看 `/api/runtime/capabilities` 和 API 启动日志

### worker 阶段日志里出现 `worker_preflight_warning=`

这代表 warning 可见，但不阻塞执行。也就是说 worker 已经启动，只是运行时检测到降级条件，在正式依赖产能或结果质量前应先修复。

### pip 兼容安装失败

- 确认你使用的是 Python `3.11`
- 重新执行 `./scripts/export_backend_requirements.sh --check`
- 一定要从仓库根目录安装，这样 `backend/requirements.txt` 中的 `./backend` 才能正确解析

### Docker 回退栈从局域网其他设备访问不到 API

在执行 `docker compose up` 前，把 `VITE_API_BASE_URL` 设置为主机的局域网地址，然后从客户端重新打开 Web UI。
