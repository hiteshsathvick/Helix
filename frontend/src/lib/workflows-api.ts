import { apiFetch, toApiError } from "./api";

// Kept in sync by hand with backend/app/modules/workflows/schemas.py's
// NODE_TYPES — same rationale as agents-api.ts's AVAILABLE_TOOLS: no
// list-node-types endpoint, and this changes rarely enough that
// duplicating it here is simpler than adding one.
export const NODE_TYPES = ["trigger", "action", "ai", "condition", "notify"] as const;

export type WorkflowNode = {
  id: string;
  type: (typeof NODE_TYPES)[number];
  config: Record<string, unknown>;
};

export type WorkflowEdge = {
  from: string;
  to: string;
  condition: "true" | "false" | null;
};

export type WorkflowGraph = {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
};

export type Workflow = {
  id: string;
  name: string;
  status: string;
  webhook_secret: string;
  created_at: string;
};

export type WorkflowVersion = {
  id: string;
  version: number;
  graph: WorkflowGraph;
  created_at: string;
};

export type WorkflowRunSummary = {
  id: string;
  workflow_id: string;
  version_id: string;
  status: string;
  trigger: Record<string, unknown>;
  created_at: string;
  finished_at: string | null;
};

export type StepRun = {
  id: string;
  node_id: string;
  node_type: string;
  status: string;
  attempts: number;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error: string | null;
  created_at: string;
};

export type WorkflowRunDetail = WorkflowRunSummary & {
  context: Record<string, unknown>;
  cost: number;
  error: string | null;
  steps: StepRun[];
};

function authedFetch(path: string, accessToken: string, options: RequestInit = {}) {
  return apiFetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers ?? {}) },
  });
}

export async function listWorkflows(accessToken: string, orgId: string): Promise<Workflow[]> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/workflows`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function getWorkflow(
  accessToken: string,
  orgId: string,
  workflowId: string
): Promise<Workflow> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/workflows/${workflowId}`, accessToken);
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function createWorkflow(
  accessToken: string,
  orgId: string,
  name: string,
  graph: WorkflowGraph
): Promise<Workflow> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/workflows`, accessToken, {
    method: "POST",
    body: JSON.stringify({ name, graph }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function updateWorkflowStatus(
  accessToken: string,
  orgId: string,
  workflowId: string,
  status: string
): Promise<Workflow> {
  const response = await authedFetch(`/api/v1/orgs/${orgId}/workflows/${workflowId}`, accessToken, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function listVersions(
  accessToken: string,
  orgId: string,
  workflowId: string
): Promise<WorkflowVersion[]> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/workflows/${workflowId}/versions`,
    accessToken
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function createVersion(
  accessToken: string,
  orgId: string,
  workflowId: string,
  graph: WorkflowGraph
): Promise<WorkflowVersion> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/workflows/${workflowId}/versions`,
    accessToken,
    { method: "POST", body: JSON.stringify({ graph }) }
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function triggerRun(
  accessToken: string,
  orgId: string,
  workflowId: string,
  input: Record<string, unknown>
): Promise<WorkflowRunSummary> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/workflows/${workflowId}/runs`,
    accessToken,
    { method: "POST", body: JSON.stringify({ input }) }
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function listRuns(
  accessToken: string,
  orgId: string,
  workflowId: string
): Promise<WorkflowRunSummary[]> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/workflows/${workflowId}/runs`,
    accessToken
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function getRun(
  accessToken: string,
  orgId: string,
  workflowId: string,
  runId: string
): Promise<WorkflowRunDetail> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/workflows/${workflowId}/runs/${runId}`,
    accessToken
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function rotateWebhookSecret(
  accessToken: string,
  orgId: string,
  workflowId: string
): Promise<Workflow> {
  const response = await authedFetch(
    `/api/v1/orgs/${orgId}/workflows/${workflowId}/webhooks/rotate`,
    accessToken,
    { method: "POST" }
  );
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
