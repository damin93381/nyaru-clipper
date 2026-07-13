# Task 10 Report — Task library and contextual inspector

## Delivered

- Added `@tanstack/react-table` and URL-backed task-library filtering with documented fallback defaults.
- Built the server-paginated task library: summary counters, debounced search, status/source/page-size filters, sortable columns, selection, confirmation-protected bulk archive/delete actions, and recoverable loading, empty, and failure states.
- Added the contextual task inspector with editable title/tags and archive control, activated by the URL `selected` value.
- Replaced the workstation’s task-library placeholder route and added workstation styles using the existing design tokens.

## Test repair

The interrupted test suite used fake timers around a React Query URL update, did not confirm the archive dialog before expecting its result, and attempted to call `unmount()` on a `QueryClient`. The repaired tests use real debounce timing, confirm the dialog, and clean up the rendered page correctly. The page retains its semantic `任务库` heading while loading so the application-router contract remains stable.

## Verification

- Focused: `corepack pnpm --dir web test --run src/workstation/features/task-library/__tests__/TaskLibraryPage.test.tsx` — 6 passed.
- Full: `corepack pnpm --dir web test --run` — 77 passed across 11 files.
- Build: `corepack pnpm --dir web build` — TypeScript and Vite production build passed.
- Production browser: captured populated and selected task-library states at 1280 px. The row selected state updated to `true`, the URL became `?selected=task-42`, and no page errors were reported.
- PNG guard: fresh populated and selected captures passed `pnpm --dir web visual:check-png` with no suspicious dark regions.

## Environment concern

This host’s headless Chromium has no Chinese-capable font installed (`fc-list :lang=zh` returned none; all declared CJK stacks resolve to DejaVu Sans), so its screenshots render Chinese text as tofu. This is host-font coverage rather than a CSS or application error; validate CJK rendering on an operator OS with the declared Noto/Source Han/PingFang/Microsoft YaHei fonts before release.

## Final review remediation — 2026-07-13

- Metadata saves now build the PATCH body from the inspector's current task snapshot, so a tags-only save transmits only `tags`. This avoids resubmitting an otherwise unchanged title that can exceed the backend title limit.
- The library now exposes a visible `标签` input with explicit apply and clear actions. Both actions update the URL-backed `tag` filter, reset to page one, and continue using the existing server-side task query contract.
- Sort state now belongs on the active table header through `aria-sort`; inactive sortable headers omit the attribute. Selection checkboxes and sortable headers have the `--ny-target-min` 44 px hit target.
- The selected inspector heading uses a compact, semantic no-wrap ellipsis treatment with the full title retained as its native title. This prevents a final CJK character such as `段` from being orphaned while preserving long-title truncation without overflow.

### TDD and verification

1. RED: focused Vitest initially failed for the intended reasons: the metadata PATCH body still contained the unchanged long title, no tag-filter textbox/action existed, and sortable headers had no `aria-sort` state.
2. GREEN: `PATH=/tmp/nyaru-node-v20.19.6/bin:$PATH pnpm --dir web test --run src/workstation/features/task-library/__tests__/TaskLibraryPage.test.tsx src/workstation/features/task-library/__tests__/TaskInspector.test.tsx` — 2 files, 9 tests passed.
3. Browser regression: `PATH=/tmp/nyaru-node-v20.19.6/bin:$PATH pnpm --dir web exec playwright test e2e/task-library-controls.spec.ts` — 1 passed. It measures both controls at 44 px or larger and verifies descending/ascending `aria-sort` transitions.
4. Full regression: `PATH=/tmp/nyaru-node-v20.19.6/bin:$PATH pnpm --dir web test --run` — 12 files, 80 tests passed.
5. Type/build: `PATH=/tmp/nyaru-node-v20.19.6/bin:$PATH pnpm --dir web exec tsc --noEmit --project tsconfig.json` and `PATH=/tmp/nyaru-node-v20.19.6/bin:$PATH pnpm --dir web build` both passed. `git diff --check` passed.

### Fresh production-preview evidence

- Captured after the final source edit at 1440 × 1000 through `FONTCONFIG_FILE=/tmp/nyaru-task10-final-evidence/fonts.conf`, which temporarily exposes `/mnt/c/Windows/Fonts` without modifying repository assets.
- Evidence: `/tmp/nyaru-task10-final-evidence/default-1440.png`, `filter-1440.png`, `selected-inspector-1440.png`, `bulk-confirm-1440.png`, and `bulk-result-1440.png`.
- `fc-match 'Microsoft YaHei UI'` resolved `msyh.ttc`; browser metadata records `bodyContainsTofu: false`, `cjkFontAvailable: true`, no console/page errors, and a selected heading with `whiteSpace: nowrap`, `textOverflow: ellipsis`, `clientHeight: 24`, and 311 px / 2000 px client/scroll widths.
- `pnpm --dir web visual:check-png` accepted all five raw PNGs with no suspicious dark regions. The initial default-state capture was discarded and recaptured after a warm-up frame to avoid transient Chromium capture corruption; the accepted files above were visually inspected for CJK glyphs, natural single-line status labels, no orphaned inspector character, and no opaque-black artifacts.
