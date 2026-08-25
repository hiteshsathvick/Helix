import { apiFetch, toApiError } from "./api";
import type { AccessTokenResponse } from "./auth-api";

export type Org = {
  id: string;
  name: string;
  slug: string;
  plan: string;
  created_at: string;
};

export type Member = {
  id: string;
  user_id: string;
  email: string;
  status: string;
  created_at: string;
};

export type InvitationCreatedResponse = {
  invitation: {
    id: string;
    email: string;
    status: string;
    expires_at: string;
    created_at: string;
  };
  token: string;
};

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function createOrg(accessToken: string, name: string, slug: string): Promise<Org> {
  const response = await authedFetch("/api/v1/orgs", accessToken, {
    method: "POST",
    body: JSON.stringify({ name, slug }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function listMyOrgs(accessToken: string): Promise<Org[]> {
  const response = await authedFetch("/api/v1/orgs", accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function listMembers(accessToken: string, orgId: string): Promise<Member[]> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/members`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function inviteMember(
  accessToken: string,
  orgId: string,
  email: string
): Promise<InvitationCreatedResponse> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/invitations`, accessToken, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function switchOrg(
  accessToken: string,
  orgId: string
): Promise<AccessTokenResponse> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/switch`, accessToken, {
    method: "POST",
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function acceptInvitation(
  accessToken: string,
  token: string
): Promise<AccessTokenResponse> {
  const response = await authedFetch(`/api/v1/invitations/${token}/accept`, accessToken, {
    method: "POST",
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
