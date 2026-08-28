import { apiFetch, toApiError } from "./api";

export type AuditLog = {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type AuditLogPage = {
  results: AuditLog[];
  next_cursor: string | null;
};

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function listAuditLogs(
  accessToken: string,
  orgId: string,
  options: { cursor?: string | null; action?: string } = {}
): Promise<AuditLogPage> {
  const params = new URLSearchParams({ limit: "20" });
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.action) params.set("action", options.action);
  const response = await authedFetch(`/api/v1/orgs/${orgId}/audit?${params}`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
