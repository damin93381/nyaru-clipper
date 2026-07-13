# Nyaru-Clipper Workstation Design System

## 0. Research Log

- Concrete product reference: the approved workstation redesign specification selects the three-column cockpit and rejects the control-room wall, video-first editor, media gallery, and linear-stage-wizard variants because they obscure operational context.
- Direction synthesis: **A structure × B material** — A is an operations-console information architecture with a persistent selection-aware inspector; B is the warm paper, fine-rule, small-radius material language of a Japanese editorial studio. The selected signature is a quiet vermilion active rule travelling through a precise paper workspace, never a neon dashboard treatment.
- Home-layout decision: rejected queue-board/Kanban and media-gallery/cover-grid homes; selected a dense, filterable operations table because the task library must scale to thousands of records.
- Embedded-reference lane: the approved specification is the visual contract; no external brand, generated image, or live-site research is used because it would weaken the locked product direction.
- Lazyweb lane: skipped — no external screen research is needed when the approved specification is the concrete reference.
- Imagen lane: skipped — this task establishes primitives, not a product-screen concept; a generated mock would not improve fidelity to the approved three-column cockpit.

## 1. Atmosphere & Identity

Nyaru-Clipper is a calm, precise desktop workstation for one operator managing media processing. Its density comes from an operations console: selection, status, queue position, and recovery remain legible at a glance. Its material comes from a Japanese editorial studio: warm paper canvas, ivory planes, fine warm-grey rules, serif titles, and small, deliberate corners. The signature is a vermilion active rule and focus response that makes the selected operation unmistakable without turning the workspace into a control-room spectacle. This system is neither cyberpunk nor generic SaaS, and it does not use glass, broad decorative gradients, pure black, or pure white.

## 2. Color

### Palette

| Role | Token | Value | Usage |
| --- | --- | --- | --- |
| Canvas | `--ny-canvas` | `#eee9de` | Page ground and quiet empty space |
| Elevated surface | `--ny-surface` | `#fdfaf3` | Panels, drawers, dialogs, menus, and inputs |
| Muted surface | `--ny-surface-muted` | `#f3eee4` | Table heads, disabled areas, secondary controls |
| Primary ink | `--ny-ink` | `#211f1a` | Headings, body, icons, and strong rules |
| Muted ink | `--ny-ink-muted` | `#756d60` | Supporting copy and technical metadata |
| Disabled ink | `--ny-ink-disabled` | `#625a4f` | Disabled controls on muted ivory; preserves 4.5:1 text contrast |
| Border | `--ny-border` | `#c9c0b0` | Fine dividers and component outlines |
| Primary accent | `--ny-accent` | `#a43c2e` | Primary action, selection, active state, destructive emphasis when paired with a label |
| Success | `--ny-success` | `#3e6755` | Successful stages and ready artifacts |
| Warning | `--ny-warning` | `#a77322` | Intervention-required and caution states |
| Warning ink | `--ny-warning-ink` | `#765015` | Warning text and icons; preserves 4.5:1 text contrast on ivory surfaces |
| Danger | `--ny-danger` | `#8f2f2f` | Failed state and destructive confirmation |
| Focus | `--ny-focus` | `#315f8a` | Keyboard focus ring only |

### Rules

- Only semantic `--ny-*` tokens are used by workstation CSS. No raw color values appear outside the token sheet.
- Accent marks an interactive or selected operation; status meaning always pairs color with text and/or an icon.
- Depth comes from tonal planes, fine rules, and a restrained warm offset shadow. Glassmorphism and broad decorative gradients are excluded.

## 3. Typography

| Role | Font stack | Usage |
| --- | --- | --- |
| Editorial serif | `"Noto Serif CJK SC", "Source Han Serif SC", "Songti SC", STSong, serif` | Page titles and media-project names |
| Interface sans | `Inter, "Noto Sans CJK SC", "Microsoft YaHei UI", "PingFang SC", sans-serif` | Controls, tables, body text, and long Chinese text |
| Technical mono | `"Cascadia Code", "JetBrains Mono", "SFMono-Regular", monospace` | Timecodes, task IDs, models, logs, and technical values |

The scale is tokenized as `--ny-font-caption` (12 px), `--ny-font-body` (14 px), `--ny-font-body-lg` (16 px), `--ny-font-section` (20 px), and `--ny-font-page` (28 px). Body text never falls below 14 px. Data uses tabular numerals. CJK copy uses natural language line breaking and must not leave a one-character final line or orphaned particle.

## 4. Spacing & Layout

### Base scale

All spacing derives from 4 px: `--ny-space-1` through `--ny-space-12` provide 4, 8, 12, 16, 20, 24, 32, 40, and 48 px steps (with omitted values intentionally unused until needed). Components use these tokens rather than arbitrary spacing.

### Desktop layouts

| Viewport | Shell | Intended behavior |
| --- | --- | --- |
| 1280 px | `224px minmax(720px, 1fr) 320px` | Three-column cockpit; main workspace owns scrolling; navigation and inspector remain sticky. |
| 1440 px | `240px minmax(800px, 1fr) 360px` | Default operational working width with denser table metadata. |
| 1920 px | `240px minmax(800px, 1fr) 360px`, surplus space remains in the main column | Avoid stretching rails; allow the operations table and inspector data to breathe. |

The first delivery supports desktop widths from 1280 px. Product screens are not forced into a mobile layout. Tables preserve readable rows and use horizontal overflow or reduced secondary detail only when later responsive requirements define it.

## 5. Components

### Button

- **Structure:** semantic `<button type="button">` with optional Lucide SVG icon and text label.
- **Variants:** primary, secondary, quiet, destructive.
- **States:** default, hover-capable, focus-visible, active, disabled, destructive.
- **Spacing:** `--ny-space-2`/`--ny-space-3`; minimum target is 44 × 44 px.
- **Accessibility:** accessible name required; disabled states use `disabled`; focus uses `--ny-focus` and does not rely on color alone.
- **Disabled treatment:** disabled text uses `--ny-ink-disabled` on `--ny-surface-muted` (5.87:1), with a not-allowed cursor and no hover response.

### Input and field message

- **Structure:** `<label>` plus `<input>` and optional supporting/error text.
- **States:** default, hover-capable, focus-visible, disabled, validation failure.
- **Accessibility:** explicit programmatic label and `aria-describedby` for support/error text; minimum 44 px target.

### Status stamp and source badge

- **Structure:** text label plus Lucide status icon; status stamp can carry `running`, `success`, `warning`, or `failed` semantics.
- **States:** selected, running, success, warning, failed.
- **Accessibility:** icon is supplementary to visible state text.

### Seven-stage progress rail

- **Structure:** ordered list of stage labels with a filled progress segment.
- **States:** selected/current, running, success, warning, failed.
- **Accessibility:** ordered stage names remain readable even if color is unavailable.

### Data-table row

- **Structure:** native table row with title, source, status, progress, and technical metadata.
- **States:** default, hover-capable, focus-visible, selected, running, success, warning, failed.
- **Accessibility:** row action has an accessible name and selected state is programmatic.

### Queue action and drag states

- **Structure:** queued rows use a real dnd-kit drag handle, an in-place active source treatment, a target insertion rule, and Radix menu actions during reorder; running rows render a concise noninteractive reason when no action is legal.
- **States:** updating is visibly announced; drag source becomes muted; before/after insertion uses the vermilion rule; disabled Radix items use muted ink, a readable tonal plane, and a not-allowed cursor without hover/focus treatment.
- **Accessibility:** pointer and keyboard drags expose the same source/insertion state; the updating message uses a text status role; inactive menu triggers are not rendered.

### Horizontally scrollable operations table

- **Structure:** a focusable, labelled table region retains the dense 1200 px table; it places a visible scroll instruction before the row interaction hint and attaches the same instruction as the region description.
- **States:** resting, keyboard focus-visible, horizontal overflow, selected, failed.
- **Accessibility:** the region is reachable with Tab and uses Left/Right Arrow to move by the current viewport; selection and task-title columns remain sticky so horizontal scanning retains task context. Keep operational columns such as progress, updated time, and storage in the data table rather than hiding them.

### Subtitle review table

- **Structure:** the review workspace keeps subtitles and candidate controls in a single reading column; subtitle rows sit inside a labelled, keyboard-reachable contained scroll region when their technical columns exceed the main pane.
- **Accessibility:** source and translated text declare their natural language and use strict CJK line breaking with phrase-aware wrapping. The main workstation pane never receives a horizontal scrollbar from review content.

### Drawer, dialog, menu, tooltip, and toast

- **Structure:** Radix primitive roots with real portal and focus handling; dialogs and drawers have a visible title and close control.
- **States:** closed, open, focus-visible, destructive confirmation where appropriate.
- **Accessibility:** Radix manages focus trapping, Escape close, menu roles, tooltip relationship, and live notification semantics; no inactive placeholder action is rendered.

### Inspected task creation flow

- **Structure:** the global Radix drawer opens from the main command bar and advances source selection → verified source preview → Standard profile and priority. Bilibili creation requires a metadata inspection; local selection is limited to opaque trusted-root IDs and relative catalog paths.
- **States:** unselected, source validation failure, inspection loading/preview, local reference or task-owned copy, field-mapped server error, submitting, and dirty-close confirmation.
- **Accessibility:** source choices are labelled buttons, catalog entries remain keyboard-operable, import modes use a radio relationship, and server errors remain next to their inputs while the operator's values stay intact.

### Loading, empty, disconnected, and failure panels

- **Structure:** status icon, concise plain-language title, reason, and a real recovery action when one exists.
- **States:** loading, empty, disconnected, failed.
- **Accessibility:** status is text-led; failures are not conveyed through color alone.

### Icon rules

Use Lucide SVG icons only, with `--ny-icon-stroke` at 1.5 px and `--ny-icon-default` at 16 px (20 px command-control size is added only when a command primitive requires it). Icons are decorative only when adjacent text repeats their meaning; otherwise they receive an accessible label. Emoji are never interface icons.

## 6. Motion & Interaction

| Token | Value | Use |
| --- | --- | --- |
| `--ny-motion-fast` | `140ms` | Button, input, and row feedback |
| `--ny-motion-base` | `200ms` | Drawer, dialog, menu, tooltip, toast, and progress state changes |

Motion explains a state change: a selected row, a focused control, a drawer entering, a menu opening, a toast arriving, or stage progress advancing. Only opacity and transform animate; layout properties do not. `prefers-reduced-motion: reduce` removes non-essential transitions. There is no decorative ambient animation.

## 7. Depth & Surface

The strategy is **mixed, ruled paper**: a small-radius ivory plane, a 1 px warm-grey rule, and a subtle 2 px warm offset shadow for elevated overlays. Baseline workspace areas rely on tonal contrast and rules rather than card stacks. Radius is intentionally restrained: `--ny-radius-1: 2px` for controls and stamps, `--ny-radius-2: 4px` for panels and overlays.

## 8. Accessibility Constraints & Accepted Debt

### Constraints

- Target WCAG 2.2 AA: minimum 4.5:1 text contrast and 3:1 large text / UI-component contrast. Focus uses a solid `--ny-focus` 3 px outline so its boundary exceeds the 3:1 component threshold on adjacent paper surfaces; warning text/icons use `--ny-warning-ink`, not the lighter warning border token.
- Every interactive control is keyboard reachable, visibly focusable, and at least 44 × 44 px.
- Modal, drawer, menu, tooltip, and toast semantics use Radix primitives with keyboard and assistive-technology behavior retained.
- Status, selection, and failure use text plus iconography as well as color.
- Dense operational views preserve 14 px minimum body text, tabular numerals, logical reading order, and plain-language recovery messages.
- Reduced-motion preference is respected. CJK strings must use natural wrapping, never clipped glyphs or isolated semantic fragments. Overlay descriptions use strict CJK line breaking and protect semantic phrase spans from wrapping internally.

### Accepted debt

| Item | Location | Why accepted | Owner / exit |
| --- | --- | --- | --- |
| OS-dependent CJK glyph rendering differences | System font stacks across supported desktop OSes | The product deliberately avoids runtime font downloads; exact glyph shapes and metrics vary by installed OS fonts while the declared fallback stacks preserve legibility. | Re-check screenshot/CJK QA on each supported operator OS before workstation cutover; no other accessibility debt is accepted. |
