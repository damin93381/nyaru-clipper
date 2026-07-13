import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import type { QueryKey } from "@tanstack/react-query";

import { cachedTaskFixture } from "./fixtures";

interface RenderWorkstationOptions {
  readonly route?: string;
  readonly seed?: readonly QueryKey[];
}

export function renderWorkstation(ui: ReactNode, options: RenderWorkstationOptions = {}): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  for (const queryKey of options.seed ?? []) {
    queryClient.setQueryData(queryKey, cachedTaskFixture);
  }

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[options.route ?? "/workstation"]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );

  return queryClient;
}
