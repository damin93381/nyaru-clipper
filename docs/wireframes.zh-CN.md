# 线框图

以下线框图只描述当前 MVP 已实现的页面和状态。

## 1. 新建任务页

路由：`/`

用途：提交一个已结束的 Bilibili VOD 链接，并进入工作台流程。

```text
+----------------------------------------------------------------------------------+
| Task intake                                                                      |
| Queue a Bilibili VOD for the canonical workstation pipeline                      |
+----------------------------------------------------------------------------------+
| New task                                                           [Single-task] |
|                                                                                  |
| Bilibili VOD URL                                                                 |
| [ https://www.bilibili.com/video/BV........                                 ]    |
|                                                                                  |
| Reserved controls                                                                |
| [x] Translation   Keep bilingual subtitle generation visible                     |
| [x] Highlight     Keep highlight analysis visible                                |
| [x] Export        Reserve clip/report export visibility                          |
|                                                                                  |
| Visible stages: Translation, Highlight, Export                                  |
| Navigation: Successful submission goes straight to /tasks/<id>                   |
|                                                                                  |
| [ Create task ]                                                                  |
+----------------------------------------------------------------------------------+
```

说明：

- 唯一必填项是 VOD 链接。
- 这些开关在当前 MVP 中只在前端可见，不会改变后端行为。
- 提交成功后会直接跳转到任务详情页。

## 2. 任务详情页：运行中状态

路由：`/tasks/:taskId`

用途：在 worker 仍在处理中时，观察标准阶段时间线。

```text
+----------------------------------------------------------------------------------+
| Task detail                                                   [running] [BV....] |
| https://www.bilibili.com/video/BV....                                           |
+---------------------------------------------+------------------------------------+
| Canonical pipeline                           | Artifacts                          |
| Stage timeline                               | Artifact overview                  |
|                                              |                                    |
| 1. ingest       [success] Attempts: 1        | source metadata                    |
| 2. media_prep   [success] Attempts: 1        | source video                       |
| 3. asr          [running] Attempts: 1        | asr audio                          |
| 4. translation  [pending] Attempts: 0        | ...                                |
| 5. highlight    [pending] Attempts: 0        |                                    |
| 6. export       [pending] Attempts: 0        |                                    |
| 7. report       [pending] Attempts: 0        |                                    |
+---------------------------------------------+------------------------------------+
| Workspace                                                                        |
| Subtitle rows and highlight cards appear here after artifacts are ready.         |
+----------------------------------------------------------------------------------+
```

说明：

- 任务运行中时轮询更频繁。
- 产物卡片会随着持久化结果写入而出现。
- 工作区保持在同一页面内，而不是跳到新的路由。

## 3. 任务详情页：失败状态

路由：`/tasks/:taskId`

用途：显示失败阶段，同时保留上游阶段的成功结果。

```text
+----------------------------------------------------------------------------------+
| Task detail                                                    [failed] [BV....] |
| https://www.bilibili.com/video/BV....                                           |
+----------------------------------------------------------------------------------+
| Readable failure summary                                                          |
| Translation stage failed                                                          |
| WhisperX model unavailable, or translation runtime failed, or other stage error. |
| Retry-ready from translation. Upstream successes remain intact.                   |
+---------------------------------------------+------------------------------------+
| Canonical pipeline                           | Artifacts                          |
| ingest       [success]                       | Already generated artifacts stay   |
| media_prep   [success]                       | visible and downloadable.          |
| asr          [success]                       |                                    |
| translation  [failed]                        |                                    |
| highlight    [pending]                       |                                    |
| export       [pending]                       |                                    |
| report       [pending]                       |                                    |
+----------------------------------------------------------------------------------+
```

说明：

- UI 会展示可读的失败摘要。
- 当前 MVP 中没有重试按钮。
- 操作人员需要借助日志与 retry API / 后端流程处理。

## 4. 工作区：复核与导出状态

路由：`/tasks/:taskId`

用途：复核双语字幕，确认高光候选，并下载结果。

```text
+----------------------------------------------------------------------------------+
| Workspace                                                                        |
+---------------------------------------------+------------------------------------+
| Subtitles                                   | Highlight candidates               |
| Segment | Chinese | Bilingual               | Rank 1  Score 0.87                 |
| seg-001 | ......  | ......                  | Reasons: subtitle density, ...     |
| seg-002 | ......  | ......                  | Default range: 120.000s -> 168.000s|
| ...                                         | Start (s) [120.000] End (s) [168.000]|
|                                             | [ Confirm export ]                 |
+---------------------------------------------+------------------------------------+
| Downloads                                                                        |
| [Download Chinese subtitles] [Download bilingual subtitles] [Download task report]|
+----------------------------------------------------------------------------------+
| Exported clips                                                                    |
| clip-00120000-00168000.mp4  Candidate 7  [Download exported clip]               |
+----------------------------------------------------------------------------------+
```

零候选变体：

```text
+--------------------------------------------------------------+
| Highlight candidates                                         |
| No highlight candidates available                            |
| No highlight candidates cleared the current scoring threshold.|
+--------------------------------------------------------------+
```

说明：

- 字幕复核和高光确认共用同一块工作区。
- 只有在用户点击 **Confirm export** 后，才会真正开始切片导出。
- 即便是零候选状态，下载区域仍然可见。
