import { apiFetch, toApiError } from "./api";

export type User = {
  id: string;
  email: string;
  is_active: boolean;
  active_org_id: string | null;
  created_at: string;
};

export type AccessTokenResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

export async function registerUser(email: string, password: string): Promise<User> {
  const response = await apiFetch("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function login(email: string, password: string): Promise<AccessTokenResponse> {
  const response = await apiFetch("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function refresh(): Promise<AccessTokenResponse> {
  const response = await apiFetch("/api/v1/auth/refresh", { method: "POST" });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function logout(): Promise<void> {
  await apiFetch("/api/v1/auth/logout", { method: "POST" });
}

export async function fetchMe(accessToken: string): Promise<User> {
  const response = await apiFetch("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
