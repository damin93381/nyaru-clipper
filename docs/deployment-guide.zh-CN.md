# 部署指南

## 适用范围

本文只覆盖本项目在本地或自托管环境中的部署方式，前提是受信任局域网或单机主机。

推荐把 `uv` 加 `pnpm` 作为主流程。Docker 保留，但只作为回退方案。

本文不扩展到云部署、公网暴露、多用户托管或 CI 编排。

## 推荐路径

| 路径 | 状态 | 适用场景 | 说明 |
| --- | --- | --- | --- |
| Linux + CUDA | 主路径 | Linux GPU 主机上的本地或自托管环境 | 面向完整项目工作流 |
| WSL + ROCm | 支持目标 | 在 WSL 内运行，且运行时能识别 `wsl-rocm` | 支持范围只覆盖 WSL2 Ubuntu 22.04 或 24.04，加官方 AMD ROCm 路径 |
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

这里的共用步骤只覆盖前端安装，以及仓库内共享的数据目录约定。

受支持的 GPU 主机路径现在都通过专用后端安装包装脚本完成依赖安装：

- Linux + CUDA：`./scripts/install_backend_linux_cuda.sh`
- WSL + ROCm：`./scripts/install_backend_wsl_rocm.sh`

在仓库根目录执行：

```bash
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

### 用专用 Linux + CUDA 包装脚本安装后端

在仓库根目录执行：

```bash
./scripts/install_backend_linux_cuda.sh
pnpm --dir web install --frozen-lockfile
```

不要把单独的 `uv sync --project backend --frozen` 当作这条路径的受支持后端安装合同。专用包装脚本会应用仓库中检查通过的 Linux CUDA 依赖配置。

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
- `APP_DEEPSEEK_API_KEY`，必需的服务端字幕校对步骤使用；绝不能设置在 `VITE_*`、浏览器存储或任务表单中

### 从 WSL 可选使用 Windows AMD AMF 导出切片

在 AMD WSL 工作站上，只有用户确认后的切片导出可以可选使用 Windows 的 AMF 媒体编码器；ASR 与媒体预处理仍在 WSL 内运行。必须显式配置 Windows 可执行文件，不能依赖刚修改过的 Windows `PATH` 能立刻被 WSL 继承：

```bash
export APP_EXPORT_VIDEO_BACKEND=windows-amf
export APP_WINDOWS_FFMPEG_BINARY='/mnt/e/Program Files/ffmpeg-N-125573-g90436de5e1-win64-gpl-shared/bin/ffmpeg.exe'
./scripts/dev_up.sh
```

请将路径替换为实际安装的 `ffmpeg.exe`。启动工作站前，先验证该 Windows 构建公开了 AMF：

```bash
"$APP_WINDOWS_FFMPEG_BINARY" -hide_banner -encoders | rg 'h264_amf'
```

导出服务会用 `wslpath -w` 转换受管的 WSL 输入/输出路径，使用 `h264_amf`，并在导出产物元数据中记录实际后端。若 AMF 配置、路径转换、进程执行或输出校验失败，服务会记录原因并仅回退一次到已有的 WSL `libx264` 命令。`APP_EXPORT_VIDEO_BACKEND` 默认仍是 `cpu`。

如果浏览器从局域网其他机器访问 Web UI，请在启动前把 `VITE_API_BASE_URL` 改成主机局域网地址，例如：

```bash
VITE_API_BASE_URL=http://192.168.1.50:8000/api ./scripts/dev_web.sh
```

## WSL + ROCm 完整功能目标

这条路径只面向 WSL2 Ubuntu 22.04 或 24.04，并且前提是你已经按 AMD 官方 WSL 指南完成 ROCm 安装。

本文不宣称支持原生 Windows GPU、原生 Linux ROCm、Docker ROCm，也不覆盖更宽泛的 WSL 发行版范围。

### 支持的 WSL 流程

WSL 路径分成四步：

1. 专用后端安装
2. 专用 doctor 自检
3. 继续复用现有 `dev_*` 脚本启动运行时
4. 专用 WSL smoke 验证

### 1. 用专用 WSL 包装脚本安装后端

在 WSL 内，从仓库根目录执行：

```bash
./scripts/install_backend_wsl_rocm.sh
pnpm --dir web install --frozen-lockfile
```

不要在 WSL 上只执行 `uv sync --project backend --frozen` 就认为后端已经安装完成。专用包装脚本会应用仓库里检查通过的 WSL ROCm 依赖路径，并为自动检测到的 AMD `gfx` 目标以 HIP 后端编译 CTranslate2 `4.8.1`。

这一步源码构建是 GPU ASR 的必要条件：PyPI 的普通 CTranslate2 wheel 只有 CUDA 后端，即使 ROCm Torch 已经能看到 GPU，WhisperX/faster-whisper 仍会回退到 CPU。首次安装因此需要 `git`、CMake、ROCm 开发库、OpenBLAS 头文件和 `readelf`，耗时也会明显长于普通依赖同步。不可变的 CTranslate2 源码缓存位于 `${XDG_CACHE_HOME:-$HOME/.cache}/nyaru-clipper/`；构建和 wheel 输出会按后端环境、AMD `gfx` 目标和 ROCm Clang 版本隔离。可用 `APP_CTRANSLATE2_BUILD_ROOT` 迁移构建输出，用 `APP_CTRANSLATE2_SOURCE_ROOT` 迁移源码缓存，或用 `APP_CTRANSLATE2_HIP_ARCHITECTURE` 覆盖 `rocminfo` 的自动目标检测。

### 2. 运行严格的 WSL doctor

在 WSL 内，从仓库根目录执行：

```bash
./scripts/check_wsl_rocm.sh
```

成功输出应包含：

- `WSL_ROCM_READY`
- `torch.build_family=rocm`
- `torch.cuda.is_available=True`
- `ctranslate2.cuda_device_count=1`
- `ctranslate2.cuda_compute_types=` 中包含 `float16`

如果这个命令失败，不要继续启动运行时，先修复 mismatch。

doctor 是快速能力门槛：它会将配置的 `APP_WHISPERX_COMPUTE_TYPE`（默认 `float16`）与 CTranslate2 可见 GPU 支持进行核对。它不能替代真实 ASR 任务；在升级 ROCm、模型版本或更换硬件后，仍应通过实际任务完成模型加载与推理的最终验证。

### `hip_build_no_device` 的 WSL 专项修复

仓库内置的 WSL profile 使用 AMD ROCm 7.2 轮子仓库，应与 ROCm 7.2 WSL 主机保持一致。ROCm 6.4 的 torch 虽然可能成功导入，但在 ROCm 7.2 主机上初始化 GPU 时可能卡住。

对于 7.13 之前的 ROCm 版本，AMD 的 ROCDXG 指引还要求设置 `HSA_ENABLE_DXG_DETECTION=1`。当共用后端启动脚本或 `check_wsl_rocm.sh` 同时检测到 WSL、`/dev/dxg` 和 `/opt/rocm/lib/librocdxg.so` 时，会自动设置该变量。若直接启动 Python 或 Uvicorn，请先执行：

```bash
export HSA_ENABLE_DXG_DETECTION=1
```

如果 `./scripts/check_wsl_rocm.sh` 报告 `hip_build_no_device`，不要立刻认定是后端装错了 torch wheel。在 WSL 主机上，即使满足下面这些条件，也仍然可能出现这个失败：

- `torch.build_family=rocm`
- `torch.version.hip` 已经有值
- `rocminfo` 已经能看到 AMD GPU

AMD 官方的 WSL PyTorch 指南给出了一条 WSL 专项修复路径：把 torch 自带的 `libhsa-runtime64.so` 替换成系统 ROCm 提供的 `/opt/rocm/lib/libhsa-runtime64.so`。

在 WSL 内、并且已经完成专用后端环境安装的前提下，从仓库根目录执行：

```bash
cp backend/.venv/lib/python3.11/site-packages/torch/lib/libhsa-runtime64.so \
  backend/.venv/lib/python3.11/site-packages/torch/lib/libhsa-runtime64.so.pre-amd-wsl

cp /opt/rocm/lib/libhsa-runtime64.so \
  backend/.venv/lib/python3.11/site-packages/torch/lib/libhsa-runtime64.so
```

然后重新执行：

```bash
./scripts/check_wsl_rocm.sh
```

在本仓库已经验证过的主机上，这个替换会把 doctor 结果从 `hip_build_no_device` 变成：

- `detected_profile=wsl-rocm`
- `torch.cuda.is_available=True`
- `torch.cuda.device_count=1`
- `WSL_ROCM_READY`

如果替换之后 doctor 仍然失败，请先收集 `rocminfo` 和 `python -m torch.utils.collect_env` 的输出，再回头修改项目代码。

### 3. 用共用入口启动运行时

WSL 继续复用和 Linux + CUDA 主路径相同的运行时启动入口：

```bash
./scripts/dev_up.sh
```

如果你要分终端运行，也继续使用：

```bash
./scripts/dev_api.sh
./scripts/dev_worker.sh
./scripts/dev_web.sh
```

项目没有单独的 WSL runtime launcher family。

### 4. 运行专用 WSL smoke 路径

在 WSL 内，从仓库根目录执行：

```bash
./scripts/release_smoke_wsl_rocm.sh
```

这个脚本会先跑 doctor，再启动共用本地栈，然后等待 `/api/health` 返回 `runtime_capabilities.detected_profile == "wsl-rocm"`，最后才进入现有下游 smoke 套件。

### 启动后检查什么

启动后用下面的命令检查完整运行时载荷：

```bash
python3 - <<'PY'
import json
import urllib.request

with urllib.request.urlopen('http://127.0.0.1:8000/api/runtime/capabilities', timeout=5) as response:
    payload = json.loads(response.read().decode('utf-8'))

print(json.dumps(payload, indent=2, ensure_ascii=False))
PY
```

对于健康的 WSL ROCm 主机，返回内容应体现：

- `detected_profile: "wsl-rocm"`
- `status: "ok"`
- `accelerator.backend: "rocm"`
- `accelerator.torch_build_family: "rocm"`
- `accelerator.available: true`
- `issues: []`

`issue_codes` 只属于 `/api/health`、启动日志、worker 预检摘要这类精简摘要视图。完整的 `/api/runtime/capabilities` 载荷暴露的是结构化 `issues` 条目。

如果启动成功但接口给出了 mismatch，请把主机视为降级状态，并使用 doctor 和日志定位具体问题：

- `wrong_torch_build_cuda_on_wsl`：已经识别到 WSL，但后端环境里还是 CUDA 版 torch。重新执行 `./scripts/install_backend_wsl_rocm.sh`。
- `cpu_only_torch_on_wsl`：已经识别到 WSL，但后端环境里是 CPU-only torch。重新执行 `./scripts/install_backend_wsl_rocm.sh`。
- `hip_build_no_device`：已经装了 ROCm torch，但 `torch.cuda` 仍然看不到 AMD GPU。先修复 WSL ROCm 栈，再重试。

遇到 `hip_build_no_device` 时，建议先执行以下运维检查：

```bash
rocminfo
ls -l /dev/dxg /dev/kfd
/home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m torch.utils.collect_env
```

如果 `rocminfo` 已经能看到 GPU，但 torch 仍然不可用，请先应用上面的 `libhsa-runtime64.so` 替换，再判断主机是否真的不受支持。

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
- `/api/health` 会附带 `runtime_capabilities`，其中包含 `status`、`detected_profile`、`warnings`、`issue_codes`，以及精简后的 `accelerator` 快照
- 完整能力信息由 `/api/runtime/capabilities` 提供
- API 启动时会在 `app.runtime` logger 写入一条 `runtime_capabilities_startup` JSON 日志
- worker 预检日志会追加 `worker_preflight_runtime=<json>`
- Web UI 也会显示运行时状态，方便操作人员不看原始日志也能发现问题

完整能力载荷的顶层键为：

- `status`
- `detected_profile`
- `platform`
- `accelerator`
- `dependencies`
- `warnings`
- `issues`

warning 的含义如下：

- 没有检测到 GPU 运行时，会报告 CPU-only warning
- 缺少 `BBDown`、`yt-dlp`、`ffmpeg`、`ffprobe` 等主机工具，会报告 warning
- 缺少可选 diarization 依赖，也会报告 warning
- 这些 warning 会同时暴露在 API、UI 和日志里
- 这些 warning 不会阻止 API 或 worker 启动

如果缺少 `torch`、`transformers`、`whisperx` 这类核心 Python 依赖，能力接口可能返回 `status: "error"`。这个状态依然是观测性的，不会把启动过程变成硬阻塞，但在补齐依赖前，系统并不适合执行真实处理任务。

## 启动后的 ASR 生命周期可观测性

当整套服务启动后，操作人员可以通过任务详情查看活动中的 ASR 生命周期状态。

这一阶段新增的可见性包括：

- 活动中的 `asr` 任务可以暴露 `execution_progress`
- 这个载荷可以显示当前 ASR phase、耗时、heartbeat 和最新进度消息
- 当 ASR 子进程还在收尾时，任务详情可以先显示 `cancel_requested`
- 只有后端仍然持有活动 `asr` 子进程的真实 tracked process group 时，才会暴露 `force-kill`

解释规则如下：

- 如果任务详情已经显示 `cancel_requested`，但阶段列表仍然显示运行中的 `asr`，应理解为取消请求已被接受，当前还在排空和清理
- 如果 `force-kill` 没有出现，不要直接判断取消能力失效，因为当前运行可能已经没有一个安全、可确认的 tracked process group 可供升级终止
- 如果后端当前没有跟踪到活动中的 ASR 执行，那么 `execution_progress` 可以完全不存在

这一阶段不会改变 CPU 或 GPU 的调优行为。当前用于保质量的模型、设备和计算默认值保持不变，性能优化工作仍然不在本阶段范围内。

## 五分钟字幕分片与必需文本校对

新任务会创建精确、任务本地的 300 秒 WAV 工作分片。单一 worker 依次运行每个分片的 WhisperX 与翻译，然后将所有字幕时间戳还原到原始视频时间轴。原始视频不会被改写。

已完成且校验通过的分片产物可以复用。重试会保留有效上游分片，仅重新处理缺失或无效的 ASR/翻译分片；从 `translation` 重试会保留有效 ASR 输出，但会先移除过期的最终双语发布结果。七个规范顶层阶段不会改变。

逐分片翻译合并后，后端向 DeepSeek 发送的任务派生数据只有双语字幕文本、稳定行 ID 与时间戳，用于必需的校对步骤。不会发送源视频、音频、Cookie、主机路径、API Key 或浏览器状态。固定的服务端提示词和原始供应商响应始终只保留在后端。浏览器只会看到安全的阶段进度/摘要，例如 `ASR 2/5`、`Translation 4/5`、`Translation merge` 和 `Translation proofread`。

仅在启动 API 与 worker 的进程环境中设置供应商 Key：

```bash
export APP_DEEPSEEK_API_KEY='请在 shell 或密钥存储中设置'
./scripts/dev_up.sh
```

不要把 Key 放入 `VITE_*` 变量、前端 `.env` 文件、任务载荷、浏览器存储、日志或产物。worker 通过配置的服务端端点使用 `deepseek-v4-flash`；浏览器中不存在供应商控制项。

如果校对期间翻译失败，请使用安全失败码和阶段日志摘要恢复：

- `translation_proofread_missing_api_key`：将 Key 添加到后端/worker 环境，重启这些进程后重试 `translation`。
- `translation_proofread_auth_failed`（401）：修正后端/worker 凭据后重试 `translation`。
- `translation_proofread_billing_failed`（402）：处理供应商账户或计费问题后重试 `translation`。
- `translation_proofread_rate_limit`、`translation_proofread_timeout` 或 `translation_proofread_transient_exhausted`：等待供应商恢复后重试 `translation`；重试次数有上限。
- `translation_proofread_invalid_response`：确认供应商恢复正常后重试 `translation`。格式错误、顺序变化、修改时间戳或空文本响应都会被拒绝，绝不会发布为最终字幕。

校对失败时，系统不会静默回退到预校对诊断字幕。高光、报告和导出只使用经验证的最终双语产物。

## 验证命令

主路径验证：

```bash
./scripts/release_smoke_non_docker.sh
```

专用 WSL ROCm 验证：

```bash
./scripts/release_smoke_wsl_rocm.sh
```

Docker 回退验证：

```bash
./scripts/release_smoke_docker.sh
```

后端 requirements 产物校验：

```bash
./scripts/export_backend_requirements.sh --check
```

修改后端任务状态、恢复逻辑或 Web 任务详情行为后，建议执行的开发者回归检查：

```bash
uv run --project backend pytest
pnpm --dir web test --run
pnpm --dir web build
pnpm --dir web exec playwright test --reporter=line
./scripts/export_backend_requirements.sh --check
```

如果本机已经有 Vite dev server 占用 `5173` 端口，请在执行 Playwright 时取消 `CI` 环境变量，让 `web/playwright.config.ts` 复用现有服务：

```bash
env -u CI pnpm --dir web exec playwright test --reporter=line
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
runtime = payload['runtime_capabilities']
assert set(runtime.keys()) == {'status', 'detected_profile', 'warnings', 'issue_codes', 'accelerator'}
PY
```

## 工作站配置与访问

Web 根路径（`/`）就是工作站任务库。桌面驾驶舱面向 1280 px 及以上宽度。仍可直接访问 `/workstation`、`/workstation/queue` 和 `/workstation/tasks/<task_id>`；旧 `/tasks/<task_id>` 链接会重定向到工作站任务概览。

### 受信任本地媒体导入根目录

本地导入默认关闭。请把 `APP_LOCAL_IMPORT_ROOTS` 设置为 API 与 worker 都可见的、已存在的绝对目录；多个目录用逗号分隔：

```bash
APP_LOCAL_IMPORT_ROOTS=/srv/media/inbox,/srv/media/archive ./scripts/dev_up.sh
```

服务端会为每个根目录分配不透明 ID，并只暴露受支持文件及安全子目录。浏览器绝不会拿到主机绝对路径。引用模式要求源文件在 ingest 前一直留在配置根目录中；复制模式会在 `data/tasks/<task-id>/raw/` 下创建任务自有源文件副本。

### 事件流后备刷新

工作站通过 `/api/v2/events` 接收任务、队列、阶段和产物的实时更新。重复重连失败后，浏览器会保留最后的快照，并每 15 秒刷新活动工作站投影。这是可见性后备机制，不会创建第二个 worker，也不会扩展队列并发。

### 受信任局域网边界

只能按本指南所述，在受信任局域网内绑定和暴露服务。工作站没有认证、TLS 终止、公网加固、限流或多用户隔离。不要添加公网反向代理，也不要把服务端口转发到互联网。

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
- 在 WSL 上，先执行 `./scripts/check_wsl_rocm.sh`，确认运行时能够识别为 `wsl-rocm`
- 在执行真实任务前，先查看 `/api/runtime/capabilities`、`/api/health` 和 API 启动日志

### API 已启动，但 WSL 暴露了 mismatch issue code

查看 `/api/health`、`/api/runtime/capabilities`、UI 环境状态卡片，以及 API 或 worker 日志中的这些精确代码：

- `wrong_torch_build_cuda_on_wsl`
- `cpu_only_torch_on_wsl`
- `hip_build_no_device`

这些状态本来就应该被暴露出来。启动不会被阻塞，但在 doctor 通过之前，这台主机都不属于受支持的 WSL ROCm 状态。

### worker 阶段日志里出现 `worker_preflight_runtime=`

这代表运行时状态已被记录下来，但不会阻塞执行。也就是说 worker 已经启动，只是运行时检测到降级条件，在正式依赖产能或结果质量前应先修复。

### pip 兼容安装失败

- 确认你使用的是 Python `3.11`
- 重新执行 `./scripts/export_backend_requirements.sh --check`
- 一定要从仓库根目录安装，这样 `backend/requirements.txt` 中的 `./backend` 才能正确解析

### Docker 回退栈从局域网其他设备访问不到 API

在执行 `docker compose up` 前，把 `VITE_API_BASE_URL` 设置为主机的局域网地址，然后从客户端重新打开 Web UI。
