import createClient from "openapi-fetch";

import type { paths } from "../../generated/api-schema";

const defaultApiBaseUrl = "http://127.0.0.1:8000/api";

export const workstationClient = createClient<paths>({
  baseUrl: (import.meta.env.VITE_API_BASE_URL ?? defaultApiBaseUrl).replace(/\/$/, ""),
});
