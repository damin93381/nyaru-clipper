# Processing Flow

## Inputs and ordered execution

One task starts from either an inspected Bilibili VOD or a supported file inside a configured trusted import root. A local task records the opaque root identity and relative path; reference mode resolves that file again at ingest, while copy mode creates a task-owned source copy before downstream processing.

The single worker claims one queued task at a time and persists the canonical flow:

```mermaid
flowchart LR
    A[Inspected Bilibili VOD or trusted local media] --> B[Ordered task queue]
    B --> C[ingest]
    C --> D[media_prep]
    D --> E[asr]
    E --> F[translation]
    F --> G[highlight]
    G --> H[export reserved for confirmed clips]
    H --> I[report]
    I --> J[Task overview and review workspace]
    J --> K{Confirm a candidate?}
    K -->|yes| L[POST /api/tasks/{task_id}/clips]
    L --> M[MP4 under task exports]
    K -->|no| N[Keep subtitles, candidates, and report]
```

`highlight` can succeed with zero candidates. The `export` stage does not automatically choose a clip; export remains an explicit operator action after review.

## Events and recovery

The v2 workstation API projects task, queue, stage, and artifact changes. The browser consumes the durable event stream at `/api/v2/events`; after five unsuccessful reconnect attempts it refreshes active workstation snapshots every 15 seconds until the stream opens again.

Recovery is backend-directed. A task overview can expose a retry action for one approved stage, or a missing-model action that downloads the required ASR models and then retries ASR. Recovery actions never expose arbitrary command execution or host paths to the browser.

## Artifact layout

```text
/data/tasks/<task-id>/
├── raw/       # managed source, including copy-mode local imports
├── work/      # prepared audio, transcripts, bilingual subtitles, candidates
├── exports/   # confirmed MP4 clips only
├── reports/   # task-report.md, including zero-candidate runs
└── logs/      # stage logs; the UI exposes safe summaries, not host paths
```

Artifact metadata is durable. A retry preserves upstream successful artifacts unless the server explicitly reruns their stage.
