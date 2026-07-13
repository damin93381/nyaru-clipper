import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { PrimitiveShowcasePage } from "../PrimitiveShowcasePage";

beforeAll(() => {
  class ResizeObserverMock {
    disconnect() {}
    observe() {}
    unobserve() {}
  }

  globalThis.ResizeObserver = ResizeObserverMock;
});

describe("PrimitiveShowcasePage", () => {
  it("renders each workstation primitive and its required state coverage", () => {
    render(<PrimitiveShowcasePage />);

    expect(screen.getByRole("heading", { name: "工作台原语" })).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "按钮" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始媒体准备" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "展开辅助说明" })).toHaveClass("ny-button--quiet");
    expect(screen.getByRole("button", { name: "不可用操作" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "标记删除" })).toBeEnabled();

    expect(screen.getByRole("heading", { name: "输入框" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "任务标题" })).toHaveAttribute("aria-describedby", "task-title-help");
    expect(screen.getByText("标题需要能让操作员在任务表中快速辨认。")).toHaveAttribute("id", "task-title-help");
    expect(screen.getByRole("textbox", { name: "需要修正的标题" })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("标题不能为空，请填写能辨认该场直播的名称。")).toHaveAttribute("id", "task-title-error");

    const statusStamps = screen.getByRole("heading", { name: "状态印记" }).closest("section");
    expect(statusStamps).not.toBeNull();
    if (statusStamps === null) {
      throw new Error("Status stamp section is missing.");
    }
    expect(within(statusStamps).getByText("处理中")).toBeInTheDocument();
    expect(within(statusStamps).getByText("已完成")).toBeInTheDocument();
    expect(within(statusStamps).getByText("需要注意")).toBeInTheDocument();
    expect(within(statusStamps).getByText("已失败")).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "进度轨道" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "流水线进度" })).toBeInTheDocument();
    expect(screen.getByText("翻译 · 需要注意")).toHaveAttribute("data-selected", "true");

    expect(screen.getByRole("heading", { name: "表格行状态" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /夏日档案/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("row", { name: /需要人工复核/i })).toHaveClass("ny-table__row--warning");
    expect(screen.getByRole("button", { name: "查看夏日档案任务" })).toBeVisible();

    expect(screen.getByRole("heading", { name: "浮层" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开侧栏" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "打开确认对话框" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "打开操作菜单" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "显示提示" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "保存队列顺序" })).toBeEnabled();

    expect(screen.getByRole("heading", { name: "反馈状态" })).toBeInTheDocument();
    expect(screen.getByText("正在读取任务元数据")).toBeInTheDocument();
    expect(screen.getByText("此视图没有匹配任务")).toBeInTheDocument();
    expect(screen.getByText("连接暂时中断")).toBeInTheDocument();
    expect(screen.getByText("字幕准备失败")).toBeInTheDocument();
  });

  it("opens overlays and reports each mutation through a closable toast", async () => {
    render(<PrimitiveShowcasePage />);

    fireEvent.click(screen.getByRole("button", { name: "开始媒体准备" }));
    expect(await screen.findByText("已开始媒体准备")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "关闭通知" }));
    expect(screen.queryByText("已开始媒体准备")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "打开确认对话框" }));
    expect(await screen.findByRole("dialog", { name: "删除派生产物？" })).toBeVisible();
    expect(document.querySelector(".ny-dialog-overlay")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "删除派生产物" }));
    expect(await screen.findByText("已删除派生产物")).toBeVisible();
  });

  it("opens the actions menu without corrupting its interactive content", async () => {
    render(<PrimitiveShowcasePage />);

    fireEvent.click(screen.getByRole("button", { name: "打开操作菜单" }));
    expect(await screen.findByRole("menuitem", { name: "归档任务" })).toBeVisible();
    fireEvent.click(screen.getByRole("menuitem", { name: "归档任务" }));
    expect(await screen.findByText("任务已归档")).toBeVisible();
  });

  it("keeps drawer and tooltip interactions keyboard-accessible", async () => {
    render(<PrimitiveShowcasePage />);

    const drawerTrigger = screen.getByRole("button", { name: "打开侧栏" });
    drawerTrigger.focus();
    fireEvent.click(drawerTrigger);
    expect(await screen.findByRole("dialog", { name: "新建任务" })).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "新建任务" })).not.toBeInTheDocument();
    await waitFor(() => expect(drawerTrigger).toHaveFocus());

    const tooltipTrigger = screen.getByRole("button", { name: "显示提示" });
    fireEvent.focus(tooltipTrigger);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("键盘焦点会保留在当前行。");
    expect(tooltipTrigger).toHaveAttribute("aria-describedby");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
