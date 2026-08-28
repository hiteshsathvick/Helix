import { apiFetch, toApiError } from "./api";

export type Webhook = {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  created_at: string;
};

export type WebhookCreatedResponse = {
  webhook: Webhook;
  secret: string; // shown exactly once
};

export type WebhookDelivery = {
  id: string;
  event_type: string;
  status: string;
  response_status: number | null;
  attempts: number;
  error: string | null;
  created_at: string;
};

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function listWebhooks(accessToken: string, orgId: string): Promise<Webhook[]> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/webhooks`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function createWebhook(
  accessToken: string,
  orgId: string,
  url: string,
  events: string[]
): Promise<WebhookCreatedResponse> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/webhooks`, accessToken, {
    method: "POST",
    body: JSON.stringify({ url, events }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function deactivateWebhook(
  accessToken: string,
  orgId: string,
  webhookId: string
): Promise<void> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/webhooks/${webhookId}`, accessToken, {
    method: "DELETE",
  });
  if (!response.ok) throw await toApiError(response);
}

export async function listDeliveries(
  accessToken: string,
  orgId: string,
  webhookId: string
): Promise<WebhookDelivery[]> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/webhooks/${webhookId}/deliveries`,
    accessToken
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
