import { apiFetch, toApiError } from "./api";

export type Notification = {
  id: string;
  channel: string;
  event_type: string;
  subject: string | null;
  body: string;
  status: string;
  read_at: string | null;
  created_at: string;
};

export type NotificationInbox = {
  results: Notification[];
  next_cursor: string | null;
};

export type NotificationPref = {
  channel: "email" | "in_app";
  event: string;
  enabled: boolean;
  frequency: "immediate" | "digest";
};

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function listInbox(
  accessToken: string,
  orgId: string,
  cursor?: string | null
): Promise<NotificationInbox> {
  const params = new URLSearchParams({ limit: "20" });
  if (cursor) params.set("cursor", cursor);
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/notifications?${params}`,
    accessToken
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function markRead(
  accessToken: string,
  orgId: string,
  notificationId: string
): Promise<Notification> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/notifications/${notificationId}/read`,
    accessToken,
    { method: "POST" }
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function markAllRead(accessToken: string, orgId: string): Promise<void> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/notifications/read-all`,
    accessToken,
    { method: "POST" }
  );
  if (!response.ok) throw await toApiError(response);
}

export async function getPrefs(accessToken: string, orgId: string): Promise<NotificationPref[]> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/notification-prefs`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function updatePrefs(
  accessToken: string,
  orgId: string,
  prefs: NotificationPref[]
): Promise<NotificationPref[]> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/notification-prefs`, accessToken, {
    method: "PUT",
    body: JSON.stringify({ prefs }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
