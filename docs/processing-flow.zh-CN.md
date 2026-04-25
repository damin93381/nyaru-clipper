# 处理流程

## 标准阶段流程

```mermaid
flowchart TD
    A[用户提交一个 Bilibili VOD 链接] --> B[创建任务、阶段和一个持久化 TaskJob]
    B --> C[ingest]
    C --> D[media_prep]
    D --> E[asr]
    E --> F[translation]
    F --> G[highlight]
    G --> H[export 阶段先标记为 skipped\n等待用户确认导出切片]
    H --> I[report]
    I --> J[任务详情页展示产物与工作区]
    J --> K{用户是否确认某个高光候选?}
    K -->|是| L[POST /api/tasks/{task_id}/clips]
    L --> M[ffmpeg 导出 MP4 到 /data/tasks/<task_id>/exports]
    K -->|否| N[任务仅保留字幕、报告和候选数据]
```

说明：

- worker 是单任务、持久化的。
- 流水线按固定标准阶段顺序运行。
- 在当前 MVP 中，切片导出是在报告生成后由用户手动触发的后续动作。
- 即使没有任何候选片段，`highlight` 阶段依然会成功结束。

## 产物目录树

```text
/data/
├── tasks.sqlite3
└── tasks/
    └── <task_id>/
        ├── raw/
        │   └── source.mp4
        ├── work/
        │   ├── asr-input.wav
        │   ├── asr-alignment-raw.json
        │   ├── asr-segments.json
        │   ├── subtitles.zh.srt
        │   ├── subtitles.zh-ja.json
        │   ├── subtitles.zh-ja.srt
        │   └── highlight-candidates.json
        ├── exports/
        │   └── clip-<start_ms>-<end_ms>.mp4
        ├── reports/
        │   └── task-report.md
        └── logs/
            ├── ingest.log
            ├── media_prep.log
            ├── asr.log
            ├── translation.log
            ├── highlight.log
            ├── export.log
            └── report.log
```

说明：

- 在用户确认导出前，`exports/` 目录会保持为空。
- 即使没有导出任何切片，`reports/task-report.md` 也会由流水线生成。
- `highlight-candidates.json` 可能包含排序后的候选片段，也可能只包含 `no_candidates` 说明。
- SQLite 中的产物元数据会指回这些磁盘路径。
