import "@testing-library/jest-dom/vitest";

class PointerEventShim extends MouseEvent {
  readonly isPrimary: boolean;
  readonly pointerId: number;

  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.isPrimary = init.isPrimary ?? true;
    this.pointerId = init.pointerId ?? 1;
  }
}

Object.defineProperty(globalThis, "PointerEvent", { configurable: true, value: PointerEventShim });
