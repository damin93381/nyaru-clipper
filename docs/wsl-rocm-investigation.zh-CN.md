# WSL + ROCm 调查记录

## 背景

目标是调查本项目为什么在 WSL 环境中没有按预期调用 ROCm。

用户已按 AMD 官方 WSL 安装指南完成 ROCm 部署，项目运行环境为：

- WSL2 / Ubuntu 22.04.5
- Linux `5.15.167.4-microsoft-standard-WSL2`
- AMD Radeon RX 7900 XTX

本次调查重点区分两类问题：

1. **主机 / 驱动 / PyTorch 环境问题**
2. **项目代码中的运行时检测 / 设备选择问题**

---

## 结论摘要

当前问题的**主要根因不在项目代码，而在 Python 运行环境**。

虽然 WSL 内的 ROCm 工具链已经能看到 AMD GPU，但项目使用的后端虚拟环境安装的是 **CUDA 版 PyTorch**，不是 **ROCm/HIP 版 PyTorch**。因此：

- `torch.version.hip` 为 `null`
- `torch.cuda.is_available()` 为 `false`
- 项目运行时检测自然只能落到 `cpu-only`

换句话说：

- **ROCm 在系统层部分可见**
- **但项目 venv 中的 torch 轮子与 ROCm 目标不匹配**
- **因此项目无法进入 `wsl-rocm` 路径**

---

## 现场证据

### 1. ROCm / WSL 系统层证据

以下结果说明 WSL 内的 ROCm 运行时至少已经能识别到 AMD GPU：

- `rocminfo` 成功执行
- 输出包含 `WSL environment detected.`
- 输出识别到 GPU：
  - `AMD Radeon RX 7900 XTX`
  - `gfx1100`
- `hipconfig --full` 显示 HIP/ROCm 已安装
- 设备节点状态：
  - `/dev/dxg` -> 存在
  - `/dev/dri` -> 存在
  - `/dev/kfd` -> 不存在

额外说明：

- `rocm-smi` 在当前 WSL 环境下没有给出正常 GPU 状态，而是报出 `Driver not initialized (amdgpu not found in modules)`。
- 但这并没有阻止 `rocminfo` 识别到 WSL GPU，因此当前更关键的问题仍然不是“完全没有 ROCm”，而是“项目 Python runtime 没有接上 ROCm”。

### 2. 项目 Python / PyTorch 证据

在测试 worktree 的后端环境中，PyTorch 实际状态如下：

- `torch.__version__ == "2.8.0+cu128"`
- `torch.version.cuda == "12.8"`
- `torch.version.hip == null`
- `torch.backends.cuda.is_built() == true`
- `torch.cuda.is_available() == false`
- `torch.cuda.device_count() == 0`

`torch.utils.collect_env` 的核心输出为：

- `PyTorch version: 2.8.0+cu128`
- `CUDA used to build PyTorch: 12.8`
- `ROCM used to build PyTorch: N/A`
- `HIP runtime version: N/A`

这已经直接证明：

> 当前项目 venv 里的 torch 是 **CUDA 构建**，不是 **ROCm 构建**。

### 3. Python 包依赖证据

已安装包元数据进一步确认当前环境偏向 NVIDIA CUDA：

- `torch` 依赖了多项 `nvidia-*` 包，例如：
  - `nvidia-cuda-runtime-cu12`
  - `nvidia-cudnn-cu12`
  - `nvidia-cublas-cu12`
  - `nvidia-cusolver-cu12`

这与 WSL + AMD ROCm 目标明显不一致。

### 4. 项目自身运行时检测结果

项目内部 `/api/runtime/capabilities` 与 `detect_runtime_profile()` 的表现与现场证据一致：

- `detected_profile: "cpu-only"`
- `accelerator.backend: "cpu"`
- `accelerator.available: false`
- `accelerator.cuda_version: "12.8"`
- `accelerator.hip_version: null`

因此当前“识别为 cpu-only”并不是误判，而是对现有 Python 环境的正确反映。

---

## 代码路径分析

### 1. 运行时检测逻辑

核心文件：`backend/app/services/runtime_profile.py`

关键逻辑：

- `_is_wsl()` 通过：
  - `WSL_DISTRO_NAME`
  - `platform.release()`
  - `platform.version()`
  - `/proc/version`
  判断是否处于 WSL
- `_detect_accelerator()` 读取：
  - `torch.version.cuda`
  - `torch.version.hip`
  - `torch.cuda.is_available()`
  - `torch.cuda.device_count()`
- `_detect_profile()` 的判定规则是：
  - WSL + HIP + GPU 可用 -> `wsl-rocm`
  - 非 WSL + CUDA + GPU 可用 -> `linux-cuda`
  - torch 在，但 GPU 不可用 -> `cpu-only`

这套逻辑和测试是自洽的，没有发现明显的判定 bug。

### 2. 模型设备选择逻辑

相关文件：

- `backend/app/settings.py`
- `backend/app/services/asr_whisperx.py`
- `backend/app/services/translation_provider.py`
- `backend/app/services/translation_hf.py`

现状：

- `whisperx_device` 默认值是 `"cuda"`
- `translation_device` 默认值也是 `"cuda"`
- WhisperX 和 Transformers provider 都直接使用这些配置值

这点需要特别说明：

> **对 ROCm PyTorch 来说，设备字符串通常仍然应该写 `cuda`。**

也就是说，这里的 `"cuda"` 默认值本身**不一定是 bug**。真正的前提是：

- 你安装的必须是 **ROCm/HIP 版 PyTorch**
- 并且 `torch.cuda.is_available()` 在 ROCm 下返回 `true`

当前环境的问题不在于设备字符串，而在于 **torch 轮子根本不是 ROCm 构建**。

---

## 官方行为对照

根据 AMD / PyTorch / WhisperX 相关资料，本次调查确认了几个关键事实：

1. **PyTorch ROCm 仍通过 `torch.cuda.*` 暴露设备接口**
   - 不是 `torch.rocm.*`
   - 也不是 `device="rocm"`

2. **判断是否为 ROCm PyTorch 的关键信号是 `torch.version.hip`**
   - 健康状态下应为非空

3. **健康的 WSL + ROCm + PyTorch 环境应满足：**
   - `rocminfo` 能看到 AMD GPU
   - `torch.cuda.is_available()` 为 `True`
   - `torch.version.hip` 非空
   - `torch.cuda.get_device_name(0)` 能返回 AMD GPU 名称

当前环境只满足第一条，不满足后面三条。

---

## 根因拆分

### A. 主机 / 环境层（主要问题）

**这是当前最主要的故障点。**

虽然 WSL 中 ROCm 已经安装并且 `rocminfo` 能看到 GPU，但项目实际创建出来的 Python 环境安装了 **PyPI 默认 CUDA 版 torch**，导致：

- 没有 HIP 支持
- 没有 `torch.version.hip`
- 没有可用的 ROCm GPU runtime
- 项目只能进入 `cpu-only`

### B. 项目代码层（次要问题）

项目代码中的运行时检测逻辑基本正确，但存在一个工程层面的不足：

- 项目会**检测并报告** ROCm / WSL 状态
- 但不会主动阻止“WSL + AMD 目标环境却装了 CUDA torch”这种错误组合

因此当前 repo 的问题更像是：

- **缺少更强的安装约束和诊断提示**

而不是：

- **runtime_profile 本身识别错误**

---

## 建议的后续动作

建议按优先级分成两步做。

### 第一优先级：修正 Python 环境

先在测试目录中把后端 venv 从当前 CUDA torch 切换到 **ROCm-compatible torch stack**，再重新验证：

- `python -c "import torch; print(torch.version.hip)"`
- `python -c "import torch; print(torch.cuda.is_available())"`
- `python -c "import torch; print(torch.cuda.get_device_name(0))"`
- `GET /api/runtime/capabilities`

预期目标：

- `torch.version.hip` 非空
- `torch.cuda.is_available()` 为 `true`
- API 返回 `detected_profile: "wsl-rocm"`

### 第二优先级：补项目文档与诊断护栏

在 repo 中补充以下内容会更稳妥：

1. **WSL + ROCm 安装路径明确说明 torch 必须使用 ROCm/HIP 构建**
2. **如果检测到 WSL 且 GPU 是 AMD，但 torch 是 CUDA wheel / HIP 缺失，则给出更明确警告**
3. **必要时在部署指南中写出 WSL + ROCm 的专用后端依赖安装方法**

---

## 一句话结论

本次问题的根因是：

> **系统层的 ROCm 已经部分可用，但项目后端虚拟环境装成了 CUDA 版 PyTorch，导致 PyTorch 无法以 HIP/ROCm 方式识别 AMD GPU，项目因此正确地回退到了 `cpu-only`。**

在修复 Python 环境之前，继续排查 WhisperX、translation provider 或 runtime profile 代码，都不会让项目真正进入 `wsl-rocm`。
