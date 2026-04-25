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

`infra/docker-compose.yml` 当前定义了三个服务：

- `api`：在 `8000` 端口运行 FastAPI
- `worker`：运行 `app.worker` 中的持久化单 worker 循环
- `web`：在 `5173` 端口运行 Vite 开发服务器

`api` 和 `worker` 复用同一个后端镜像，并共享同一套存储挂载，因此它们会看到同一个 SQLite 数据库和同一棵任务产物目录树。

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

在仓库根目录执行：

```bash
docker compose -f infra/docker-compose.yml up --build
```

常用覆盖环境变量：

- `API_BIND_ADDRESS`：修改 API 绑定地址，默认 `0.0.0.0`
- `WEB_BIND_ADDRESS`：修改 Web 绑定地址，默认 `0.0.0.0`
- `VITE_API_BASE_URL`：让浏览器访问正确的主机 API 地址
- `APP_BILIBILI_COOKIE_PATH`：指定容器内 Bilibili Cookie 文件路径

### Web UI 的局域网访问说明

默认 `VITE_API_BASE_URL` 为 `http://127.0.0.1:8000/api`。

当浏览器和 Docker 在同一台机器上时，这样配置是可行的。如果使用者从局域网其他设备打开 UI，请在启动前把 `VITE_API_BASE_URL` 改成主机的局域网地址，例如：

```bash
VITE_API_BASE_URL=http://192.168.1.50:8000/api docker compose -f infra/docker-compose.yml up --build
```

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

当前 MVP 假设部署在一台 NVIDIA GPU 主机上。

Compose 中设置了：

- `NVIDIA_VISIBLE_DEVICES`
- `NVIDIA_DRIVER_CAPABILITIES`
- `api` 与 `worker` 的 GPU 预留配置

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

## 日志与排障

每个任务的阶段日志位于 `/data/tasks/<task_id>/logs/<stage>.log`。

任务失败时建议按以下顺序排查：

1. 先在 UI 或 `/api/tasks/<task_id>/stages` 中确认失败阶段
2. 打开对应的 `/data/tasks/<task_id>/logs/<stage>.log`
3. 检查模型缓存是否已下载且具有可读权限
4. 如果 Bilibili 访问失败，检查 Cookie 是否可用
5. 检查容器内媒体工具是否可解析，例如：

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
