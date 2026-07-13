import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, MoreHorizontal } from "lucide-react";
import type { DragEndEvent } from "@dnd-kit/core";
import type { ReactNode } from "react";

import type { QueueItem, QueueSnapshot, QueueState } from "./api";

interface QueueListProps {
  readonly isMutating: boolean;
  readonly onReorder: (orderedTaskIds: readonly string[]) => void;
  readonly onSelect: (taskId: string) => void;
  readonly onSetState: (taskId: string, state: QueueState) => void;
  readonly selectedTaskId: string | null;
  readonly snapshot: QueueSnapshot;
}

interface QueueRowProps {
  readonly canMoveDown: boolean;
  readonly canMoveUp: boolean;
  readonly isMutating: boolean;
  readonly item: QueueItem;
  readonly onMove: (taskId: string, direction: "down" | "first" | "up") => void;
  readonly onSelect: (taskId: string) => void;
  readonly onSetState: (taskId: string, state: QueueState) => void;
  readonly selected: boolean;
  readonly sortable: boolean;
  readonly queuedTaskIds: readonly string[];
}

type QueueInsertion = "after" | "before";

interface QueueActionsProps {
  readonly canMoveDown: boolean;
  readonly canMoveUp: boolean;
  readonly isMutating: boolean;
  readonly item: QueueItem;
  readonly onMove: (taskId: string, direction: "down" | "first" | "up") => void;
  readonly onSetState: (taskId: string, state: QueueState) => void;
  readonly sortable: boolean;
}

function QueueActions({ canMoveDown, canMoveUp, isMutating, item, onMove, onSetState, sortable }: QueueActionsProps): ReactNode {
  const hasAvailableAction = (sortable && (canMoveUp || canMoveDown || item.state === "queued")) || item.state === "paused";

  if (!hasAvailableAction) return <span className="ny-queue__unavailable">执行中，当前不可调整。</span>;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild><button aria-label={`${item.task_id} 操作`} className="ny-button ny-button--quiet" disabled={isMutating} type="button"><MoreHorizontal aria-hidden="true" size="var(--ny-icon-default)" /></button></DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="ny-menu ny-menu--content" sideOffset={4}>
          <DropdownMenu.Item className="ny-menu-item" disabled={isMutating || !sortable || !canMoveUp} onSelect={() => onMove(item.task_id, "up")}>上移</DropdownMenu.Item>
          <DropdownMenu.Item className="ny-menu-item" disabled={isMutating || !sortable || !canMoveDown} onSelect={() => onMove(item.task_id, "down")}>下移</DropdownMenu.Item>
          <DropdownMenu.Item className="ny-menu-item" disabled={isMutating || !sortable || !canMoveUp} onSelect={() => onMove(item.task_id, "first")}>移到队首</DropdownMenu.Item>
          <DropdownMenu.Item className="ny-menu-item" disabled={isMutating || item.state !== "queued"} onSelect={() => onSetState(item.task_id, "paused")}>暂停</DropdownMenu.Item>
          <DropdownMenu.Item className="ny-menu-item" disabled={isMutating || item.state !== "paused"} onSelect={() => onSetState(item.task_id, "queued")}>恢复</DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function QueueRow({ canMoveDown, canMoveUp, isMutating, item, onMove, onSelect, onSetState, queuedTaskIds, selected, sortable }: QueueRowProps): ReactNode {
  const { active, attributes, isDragging, isOver, listeners, setNodeRef, transform, transition } = useSortable({ disabled: !sortable || isMutating, id: item.task_id });
  const style = sortable ? { transform: CSS.Transform.toString(transform), transition } : undefined;
  const activeTaskId = active === null ? null : String(active.id);
  const insertion = isOver && activeTaskId !== null && activeTaskId !== item.task_id
    ? (queuedTaskIds.indexOf(activeTaskId) < queuedTaskIds.indexOf(item.task_id) ? "after" : "before") satisfies QueueInsertion
    : null;

  return (
    <tr aria-selected={selected} className={isDragging ? "ny-queue__row--dragging" : undefined} data-queue-drag-source={isDragging ? "true" : undefined} data-queue-insertion={insertion ?? undefined} onClick={(event) => {
      if (event.target instanceof HTMLElement && event.target.closest("button, [role=menuitem]")) return;
      onSelect(item.task_id);
    }} ref={setNodeRef} style={style}>
      <td><button aria-label={`拖动 ${item.task_id}`} className="ny-button ny-button--quiet" disabled={!sortable || isMutating} type="button" {...attributes} {...listeners}><GripVertical aria-hidden="true" size="var(--ny-icon-default)" /></button></td>
      <td className="ny-table__technical"><button aria-label={`选择 ${item.task_id}`} aria-pressed={selected} className="ny-queue__selection-action" onClick={() => onSelect(item.task_id)} type="button">{item.task_id}</button></td>
      <td>{item.state === "running" ? "正在执行" : item.state === "paused" ? "已暂停" : "等待处理"}</td>
      <td>{item.state === "queued" ? item.position : "—"}</td>
      <td>{item.priority}</td>
      <td><QueueActions canMoveDown={canMoveDown} canMoveUp={canMoveUp} isMutating={isMutating} item={item} onMove={onMove} onSetState={onSetState} sortable={sortable} /></td>
    </tr>
  );
}

export function QueueList({ isMutating, onReorder, onSelect, onSetState, selectedTaskId, snapshot }: QueueListProps): ReactNode {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const queuedTaskIds = snapshot.queued.map((item) => item.task_id);

  function move(taskId: string, direction: "down" | "first" | "up"): void {
    if (isMutating) return;
    const from = queuedTaskIds.indexOf(taskId);
    if (from < 0) return;
    const to = direction === "first" ? 0 : direction === "up" ? from - 1 : from + 1;
    if (to < 0 || to >= queuedTaskIds.length || to === from) return;
    onReorder(arrayMove(queuedTaskIds, from, to));
  }

  function handleDragEnd(event: DragEndEvent): void {
    if (isMutating) return;
    const overId = event.over?.id ?? event.collisions?.[0]?.id;
    if (overId === undefined || event.active.id === overId) return;
    const from = queuedTaskIds.indexOf(String(event.active.id));
    const to = queuedTaskIds.indexOf(String(overId));
    if (from >= 0 && to >= 0) onReorder(arrayMove(queuedTaskIds, from, to));
  }

  return (
    <section className="ny-showcase__section" aria-labelledby="queue-list-title" aria-busy={isMutating}>
      <div><p className="ny-workstation__eyebrow">手动调度</p><h2 className="ny-showcase__section-heading" id="queue-list-title">等待队列</h2></div>
      {isMutating ? <p className="ny-queue__updating" role="status">正在保存队列更改。</p> : null}
      {snapshot.active ? <><p className="ny-workstation__eyebrow">执行中</p><table className="ny-table"><tbody><QueueRow canMoveDown={false} canMoveUp={false} isMutating={isMutating} item={snapshot.active} onMove={move} onSelect={onSelect} onSetState={onSetState} queuedTaskIds={queuedTaskIds} selected={selectedTaskId === snapshot.active.task_id} sortable={false} /></tbody></table></> : null}
      <DndContext collisionDetection={closestCenter} onDragEnd={handleDragEnd} sensors={sensors}>
        <SortableContext items={queuedTaskIds} strategy={verticalListSortingStrategy}>
          <table className="ny-table"><thead><tr><th scope="col">排序</th><th scope="col">任务</th><th scope="col">状态</th><th scope="col">位置</th><th scope="col">优先级</th><th scope="col">操作</th></tr></thead><tbody>{snapshot.queued.map((item, index) => <QueueRow canMoveDown={index < snapshot.queued.length - 1} canMoveUp={index > 0} isMutating={isMutating} item={item} key={item.task_id} onMove={move} onSelect={onSelect} onSetState={onSetState} queuedTaskIds={queuedTaskIds} selected={selectedTaskId === item.task_id} sortable />)}</tbody></table>
        </SortableContext>
      </DndContext>
      {snapshot.paused.length > 0 ? <><p className="ny-workstation__eyebrow">已暂停</p><table className="ny-table"><tbody>{snapshot.paused.map((item) => <QueueRow canMoveDown={false} canMoveUp={false} isMutating={isMutating} item={item} key={item.task_id} onMove={move} onSelect={onSelect} onSetState={onSetState} queuedTaskIds={queuedTaskIds} selected={selectedTaskId === item.task_id} sortable={false} />)}</tbody></table></> : null}
    </section>
  );
}
