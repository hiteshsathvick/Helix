import { apiFetch, toApiError } from "./api";

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  last_used_at: string | null;
  created_at: string;
};

export type ApiKeyCreatedResponse = {
  key: ApiKey;
  raw_key: string; // shown exactly once
};

export const AVAILABLE_SCOPES = ["search:read", "documents:read", "documents:write"] as const;

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function listApiKeys(accessToken: string, orgId: string): Promise<ApiKey[]> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/api-keys`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function createApiKey(
  accessToken: string,
  orgId: string,
  name: string,
  scopes: string[]
): Promise<ApiKeyCreatedResponse> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/api-keys`, accessToken, {
    method: "POST",
    body: JSON.stringify({ name, scopes }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function revokeApiKey(
  accessToken: string,
  orgId: string,
  keyId: string
): Promise<void> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/api-keys/${keyId}`, accessToken, {
    method: "DELETE",
  });
  if (!response.ok) throw await toApiError(response);
}
