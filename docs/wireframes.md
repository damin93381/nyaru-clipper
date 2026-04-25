# Wireframes

These wireframes describe the current MVP screens and states only.

## 1. New task page

Route: `/`

Purpose: submit one completed Bilibili VOD URL and move into the workstation flow.

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
| [x] Export        Reserve clip/report export visibility                           |
|                                                                                  |
| Visible stages: Translation, Highlight, Export                                  |
| Navigation: Successful submission goes straight to /tasks/<id>                   |
|                                                                                  |
| [ Create task ]                                                                  |
+----------------------------------------------------------------------------------+
```

Annotations:

- The only required field is the VOD URL.
- The toggle cards are visible but UI-local in this MVP.
- Successful submission navigates directly to the task detail route.

## 2. Task detail page, running state

Route: `/tasks/:taskId`

Purpose: watch the canonical stage timeline while the worker is still processing.

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

Annotations:

- Polling is fast while the task is active.
- Artifact cards appear as durable outputs are persisted.
- The workspace stays on the same page instead of opening a new route.

## 3. Task detail page, failed state

Route: `/tasks/:taskId`

Purpose: show the stage that failed and keep upstream successes visible.

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

Annotations:

- The UI shows a human-readable failure summary.
- There is no retry button in the current MVP UI.
- Operators use logs and the retry API/backend workflow.

## 4. Workspace review and export state

Route: `/tasks/:taskId`

Purpose: review bilingual subtitles, confirm a highlight candidate, and download outputs.

```text
+----------------------------------------------------------------------------------+
| Workspace                                                                        |
+---------------------------------------------+------------------------------------+
| Subtitles                                   | Highlight candidates               |
| Segment | Chinese | Bilingual               | Rank 1  Score 0.87                 |
| seg-001 | ......  | ......                  | Reasons: subtitle density, ...     |
| seg-002 | ......  | ......                  | Default range: 120.000s -> 168.000s|
| ...                                        | Start (s) [120.000] End (s) [168.000]|
|                                             | [ Confirm export ]                 |
+---------------------------------------------+------------------------------------+
| Downloads                                                                        |
| [Download Chinese subtitles] [Download bilingual subtitles] [Download task report]|
+----------------------------------------------------------------------------------+
| Exported clips                                                                    |
| clip-00120000-00168000.mp4  Candidate 7  [Download exported clip]               |
+----------------------------------------------------------------------------------+
```

Zero-candidate variation:

```text
+--------------------------------------------------------------+
| Highlight candidates                                         |
| No highlight candidates available                            |
| No highlight candidates cleared the current scoring threshold.|
+--------------------------------------------------------------+
```

Annotations:

- Subtitle review and highlight confirmation share one workstation area.
- Clip export only starts after the user clicks **Confirm export**.
- Downloads remain visible even when there are zero candidates.
