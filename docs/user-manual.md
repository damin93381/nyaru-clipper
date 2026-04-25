# User Manual

## What this workstation does

This MVP accepts one completed Bilibili VOD URL at a time.

For each task, the workstation can:

- download the source video
- generate Chinese timed subtitles
- generate Chinese and Japanese bilingual subtitles
- score highlight candidates for review
- export an MP4 clip after you confirm a candidate
- generate a Markdown task report

This MVP does not record live streams, watch channels, manage subscriptions, or publish clips for you.

## Before you start

- Use a completed Bilibili VOD URL.
- Open the WebUI from a trusted LAN device.
- If the source video is private, member-only, or region-limited, ask the operator to provide a valid Bilibili cookie file before you submit the task.

## Submit a task

1. Open the WebUI, usually at `http://<host>:5173`.
2. On the **Task intake** page, paste the Bilibili VOD URL into **Bilibili VOD URL**.
3. Leave the visible processing toggles on. In this MVP they are informational and do not change the backend pipeline.
4. Click **Create task**.
5. The UI sends you straight to `/tasks/<task_id>`.

## Watch task progress

The task detail page shows the canonical stages in order:

1. `ingest`
2. `media_prep`
3. `asr`
4. `translation`
5. `highlight`
6. `export`
7. `report`

What to expect:

- While the task is active, the page refreshes often.
- After the task reaches a terminal state, the refresh cadence slows down.
- The **Stage timeline** tells you which stage is running, finished, skipped, or failed.
- The **Artifact overview** fills in as durable outputs are saved.

If a task fails, the page shows a readable failure summary for the stage that stopped the run. In this MVP, ask the operator to investigate and retry from the backend/API side.

## Review subtitles and highlight candidates

The lower half of the task detail page is the workstation area.

### Subtitle review

The **Subtitle review and highlight confirmation** section shows:

- segment ID
- timestamp range
- Chinese subtitle text
- bilingual subtitle text, when translation is available

Use this area to check timing and translation quality before exporting any clip.

### Highlight review

The **Ranked candidate confirmation** panel shows:

- rank
- score
- source range
- reason labels
- editable start and end seconds

If no highlight candidates pass the threshold, the UI shows a zero-candidate message instead of hiding the result. You can still download subtitles and the task report in that case.

## Confirm clip export

Clip export is manual in this MVP.

1. Find the highlight candidate you want to keep.
2. Review the suggested time range.
3. Adjust **Start (s)** and **End (s)** if needed.
4. Click **Confirm export**.
5. Wait for the exported clip card to appear.

Notes:

- The system does not auto-export clips at task completion.
- Export creates an MP4 clip for the confirmed range.
- If the range is invalid, the UI shows the backend validation error.

## Download artifacts

The **Artifact downloads** area can expose these links:

- Chinese subtitles
- bilingual subtitles
- Chinese transcript JSON
- bilingual transcript JSON
- task report
- exported clip

The **Exported clips** area shows confirmed MP4 files after clip export succeeds.

Common cases:

- If no candidate is confirmed, you will not see an exported clip.
- If no highlight candidates are found, subtitles and the report can still be available.

## MVP boundaries

This manual only covers the current MVP.

Not included:

- live recording
- recurring jobs
- subscriptions
- public internet deployment
- multi-user accounts or approval queues
