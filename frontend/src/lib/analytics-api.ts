import { apiFetch, toApiError } from "./api";
import type { UsageSummary } from "./billing-api";

export type AnalyticsOverview = {
  month: string;
  usage: UsageSummary;
  agent_runs_by_status: Record<string, number>;
  workflow_runs_by_status: Record<string, number>;
  documents_by_status: Record<string, number>;
  active_users: number;
};

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function getAnalyticsOverview(
  accessToken: string,
  orgId: string
): Promise<AnalyticsOverview> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/analytics/overview`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
