# User Manual

## Workstation overview

Nyaru-Clipper opens on the desktop **Task library** at `/`. It is a single-operator workstation for completed Bilibili VODs and media files already visible to the host. The library, queue, task overview, review workspace, and recovery controls stay in one three-column cockpit.

This MVP runs one GPU-bound pipeline job at a time. It does not record live streams, publish clips, provide accounts, or support public-internet operation.

## Create a task

Select **New task** in the command bar. The drawer always validates the source before a task is created.

- **Bilibili VOD**: paste an HTTPS `bilibili.com` URL (including an approved subdomain) with a `/video/BV…` path, select **Inspect source**, confirm the title/uploader preview, then choose Standard and a priority. Short links and HTTP URLs are deliberately rejected and never resolved by the workstation.
- **Local file**: browse only the operator-configured import roots. Select a supported media file and choose either **Reference original file** or **Copy into task storage**. The browser receives an opaque root ID and a relative catalog path; it never receives the host path.

Creating the task puts it in the ordered single-GPU queue and opens `/workstation/tasks/<task_id>`.

## Operate the task library and queue

The library scales through search, status/source/date/readiness filters, tags, sorting, and pagination. Select rows to inspect one task in the persistent right-hand context panel or to perform a supported bulk action.

**Processing queue** is the manual ordering surface. Only queued work can be moved. Drag a queued row or use its keyboard-accessible action menu. If another operation changed the queue first, the workstation restores the authoritative order and tells you that the reorder was not applied.

## Follow a task and recover failures

The task overview has a seven-stage rail:

1. `ingest`
2. `media_prep`
3. `asr`
4. `translation`
5. `highlight`
6. `export`
7. `report`

Select a stage to update the safe-log and artifact inspector. When the backend supplies a recovery action, the overview exposes only that action. For example, a missing ASR model can be downloaded and then retried from ASR; a failed stage can be retried from the server-approved stage. Upstream artifacts remain available.

The connection banner reports live workstation events. After repeated event-stream failures, the UI keeps its snapshot and falls back to refreshing it every 15 seconds; it returns to real-time updates after the stream reconnects.

## Review and export

The overview includes the existing review workspace:

- inspect Chinese and Japanese subtitles in the contained table;
- review ranked highlight candidates and adjust start/end seconds;
- select **Confirm export** to create one MP4 for the confirmed range;
- download subtitles, reports, and exported clips once their artifacts are ready.

A zero-candidate result is still a successful highlight stage: subtitles and the report can remain downloadable even when there is no clip to export.

## Trusted-LAN boundary

Use the workstation only on a trusted LAN or the host itself. It intentionally has no authentication, TLS termination, rate limiting, tenant isolation, or public exposure controls. Do not port-forward it or expose it directly to the internet.

## Route compatibility

`/` is the workstation library. `/workstation`, `/workstation/queue`, and `/workstation/tasks/<task_id>` remain direct workstation URLs. Old `/tasks/<task_id>` links redirect to the corresponding workstation overview.
