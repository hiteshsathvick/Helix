import { apiFetch, toApiError } from "./api";

export type Connector = {
  id: string;
  type: string;
  name: string;
  // "active" (connected/idle) | "syncing" | "error"
  status: string;
  last_synced_at: string | null;
  last_sync_error: string | null;
  created_at: string;
};

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function listConnectors(accessToken: string, orgId: string): Promise<Connector[]> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/connectors`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function createWebConnector(
  accessToken: string,
  orgId: string,
  name: string,
  urlList: string[]
): Promise<Connector> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/connectors`, accessToken, {
    method: "POST",
    body: JSON.stringify({ name, url_list: urlList }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function startGitHubAuthorize(
  accessToken: string,
  orgId: string,
  repo: string,
  branch: string
): Promise<string> {
  const params = new URLSearchParams({ repo, branch });
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/connectors/github/authorize?${params}`,
    accessToken
  );
  if (!response.ok) throw await toApiError(response);
  const body: { authorize_url: string } = await response.json();
  return body.authorize_url;
}

export async function triggerSync(
  accessToken: string,
  orgId: string,
  connectorId: string
): Promise<Connector> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/connectors/${connectorId}/sync`,
    accessToken,
    { method: "POST" }
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function disconnectConnector(
  accessToken: string,
  orgId: string,
  connectorId: string
): Promise<void> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/connectors/${connectorId}`,
    accessToken,
    { method: "DELETE" }
  );
  if (!response.ok) throw await toApiError(response);
}
