import { render, screen } from "@testing-library/react";

import App from "../App";


describe("workspace smoke", () => {
  it("renders the bootstrap shell", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: /bilibili vtuber suite/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /queue a bilibili vod for the canonical workstation pipeline/i })).toBeInTheDocument();
  });
});
