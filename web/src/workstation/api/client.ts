import createClient from "openapi-fetch";

import type { paths } from "../../generated/api-schema";

const defaultApiOrigin = "http://127.0.0.1:8000";

function normalizeApiOrigin(configuredBaseUrl: string): string {
  return configuredBaseUrl.replace(/\/+$/, "").replace(/\/api$/, "");
}

export const workstationClient = createClient<paths>({
  baseUrl: normalizeApiOrigin(import.meta.env.VITE_API_BASE_URL ?? defaultApiOrigin),
});
