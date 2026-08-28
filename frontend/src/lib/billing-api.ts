import { apiFetch, toApiError } from "./api";

export type BillingSummary = {
  plan: string;
  status: string;
  seats_used: number;
  seats_limit: number | null;
  monthly_cost_cap_usd: number | null;
};

export type UsageByKind = {
  kind: string;
  quantity: number;
  cost_usd: number;
};

export type UsageSummary = {
  month: string;
  items: UsageByKind[];
  total_cost_usd: number;
  monthly_cost_cap_usd: number | null;
};

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function getBillingSummary(
  accessToken: string,
  orgId: string
): Promise<BillingSummary> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/billing`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function startCheckout(
  accessToken: string,
  orgId: string,
  plan: "pro" | "enterprise"
): Promise<string> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/billing/checkout`, accessToken, {
    method: "POST",
    body: JSON.stringify({ plan }),
  });
  if (!response.ok) throw await toApiError(response);
  const body: { checkout_url: string } = await response.json();
  return body.checkout_url;
}

export async function cancelSubscription(accessToken: string, orgId: string): Promise<void> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/billing/cancel`, accessToken, {
    method: "POST",
  });
  if (!response.ok) throw await toApiError(response);
}

export async function getUsageSummary(
  accessToken: string,
  orgId: string
): Promise<UsageSummary> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/usage`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
