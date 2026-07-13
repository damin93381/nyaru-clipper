import { render, screen, within } from "@testing-library/react";

import { PrimitiveShowcasePage } from "../PrimitiveShowcasePage";

describe("PrimitiveShowcasePage", () => {
  it("renders the workstation primitive catalog and its interactive examples", () => {
    render(<PrimitiveShowcasePage />);

    expect(screen.getByRole("heading", { name: "Workstation primitives" })).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Buttons" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Primary action" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Disabled action" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Destructive action" })).toBeEnabled();

    expect(screen.getByRole("heading", { name: "Inputs" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Task title" })).toBeEnabled();

    const statusStamps = screen.getByRole("heading", { name: "Status stamps" }).closest("section");
    expect(statusStamps).not.toBeNull();
    if (statusStamps === null) {
      throw new Error("Status stamp section is missing.");
    }
    expect(within(statusStamps).getByText("Running")).toBeInTheDocument();
    expect(within(statusStamps).getByText("Succeeded")).toBeInTheDocument();
    expect(within(statusStamps).getByText("Needs attention")).toBeInTheDocument();
    expect(within(statusStamps).getByText("Failed")).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Progress rail" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Pipeline progress" })).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Table row states" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /selected task/i })).toHaveAttribute("aria-selected", "true");

    expect(screen.getByRole("heading", { name: "Overlays" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open drawer" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Open confirmation dialog" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Open actions menu" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Show tooltip" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Show toast" })).toBeEnabled();

    expect(screen.getByRole("heading", { name: "Feedback states" })).toBeInTheDocument();
    expect(screen.getByText("Loading task metadata")).toBeInTheDocument();
    expect(screen.getByText("No tasks match this view")).toBeInTheDocument();
    expect(screen.getByText("Connection interrupted")).toBeInTheDocument();
    expect(screen.getByText("Transcript preparation failed")).toBeInTheDocument();
  });
});
