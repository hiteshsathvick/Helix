import { apiFetch, toApiError } from "./api";

// Kept in sync by hand with app/modules/agents/tools.py's TOOLS registry —
// there's no list-tools endpoint (not in Phase 12's scope), and this list
// changes rarely enough that duplicating it here is simpler than adding one.
export const AVAILABLE_TOOLS = ["search", "fetch_document", "http_request", "notify"] as const;

export type Agent = {
  id: string;
  name: string;
  instructions: string;
  allowed_tools: string[];
  created_at: string;
};

export type AgentRunSummary = {
  id: string;
  agent_id: string;
  status: string;
  created_at: string;
  finished_at: string | null;
};

export type AgentStep = {
  id: string;
  ordinal: number;
  type: string;
  tool: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  created_at: string;
};

export type AgentRunDetail = AgentRunSummary & {
  input: string;
  output: string | null;
  error: string | null;
  tokens: number;
  cost: number;
  steps: AgentStep[];
};

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function listAgents(accessToken: string, orgId: string): Promise<Agent[]> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/agents`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function createAgent(
  accessToken: string,
  orgId: string,
  name: string,
  instructions: string,
  allowedTools: string[]
): Promise<Agent> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/agents`, accessToken, {
    method: "POST",
    body: JSON.stringify({ name, instructions, allowed_tools: allowedTools }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function triggerRun(
  accessToken: string,
  orgId: string,
  agentId: string,
  input: string
): Promise<AgentRunSummary> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/agents/${agentId}/runs`,
    accessToken,
    { method: "POST", body: JSON.stringify({ input }) }
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function listRuns(
  accessToken: string,
  orgId: string,
  agentId: string
): Promise<AgentRunSummary[]> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/agents/${agentId}/runs`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function getRun(
  accessToken: string,
  orgId: string,
  agentId: string,
  runId: string
): Promise<AgentRunDetail> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/agents/${agentId}/runs/${runId}`,
    accessToken
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
