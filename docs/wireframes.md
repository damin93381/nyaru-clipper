# Workstation wireframes

The approved desktop architecture is a warm-paper, three-column cockpit. It targets 1280 px and wider screens; it is not a mobile layout.

## Task library (`/` and `/workstation`)

```text
+----------------------+----------------------------------------------+----------------------+
| Nyaru-Clipper        | [ New task ]                                  | Context inspector    |
| Task library          | Task library                                  | selected task /      |
| Processing queue      | [ search ][ filters ][ tags ][ page size ]    | active GPU work      |
|                      +----------------------------------------------+                      |
|                      | operations table: task / source / status /   | safe metadata,       |
|                      | progress / updated / storage                  | never host paths     |
|                      | [bulk actions]                    [pagination]|                      |
+----------------------+----------------------------------------------+----------------------+
```

Loading, empty, disconnected, and failed states use a text-led feedback panel. Dense tables keep task context visible and own any necessary contained horizontal scroll.

## Queue (`/workstation/queue`)

```text
+----------------------+----------------------------------------------+----------------------+
| navigation            | Queue version n                              | selected queue item  |
|                      | active job (not movable)                     | task ID, state,      |
|                      | queued rows [drag] [keyboard action menu]    | position, priority   |
|                      | paused rows                                   |                      |
|                      | conflict → authoritative order + status text  |                      |
+----------------------+----------------------------------------------+----------------------+
```

Only queued work is movable. Pointer and keyboard reordering share the same visible insertion and updating states.

## Task overview (`/workstation/tasks/:taskId`)

```text
+----------------------+----------------------------------------------+----------------------+
| navigation            | task title / status                           | safe logs and        |
|                      | seven-stage rail                              | stage artifacts      |
|                      | recovery action, when supplied by backend     |                      |
|                      | subtitles (contained scroll)                  |                      |
|                      | ranked candidates → [confirm export]          |                      |
|                      | downloads and exported MP4s                   |                      |
+----------------------+----------------------------------------------+----------------------+
```

The stage rail selects the inspector context. A missing-model or retry action is shown only when it is supplied by the backend. Legacy `/tasks/:taskId` links redirect here.

## New-task drawer

```text
source choice → inspected Bilibili preview OR trusted local catalog
             → reference original / copy to task storage
             → Standard profile + priority → create task → task overview
```

The drawer traps focus, returns focus on close, asks before discarding a dirty draft, and preserves values beside mapped server errors.
