"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Alert, Button, EmptyState, Spinner } from "@/components/ui";
import { WorkflowGraphBuilder } from "@/components/WorkflowGraphBuilder";
import { useAuth } from "@/lib/auth-context";
import { getMyPermissions } from "@/lib/orgs-api";
import {
  createVersion,
  getWorkflow,
  listRuns,
  listVersions,
  rotateWebhookSecret,
  triggerRun,
  updateWorkflowStatus,
  type WorkflowGraph,
} from "@/lib/workflows-api";

export default function WorkflowDetailPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string; workflowId: string }>();
  const orgId = params.id;
  const workflowId = params.workflowId;
  const queryClient = useQueryClient();

  const [editingGraph, setEditingGraph] = useState<WorkflowGraph | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const workflowQuery = useQuery({
    queryKey: ["workflow", orgId, workflowId, accessToken],
    queryFn: () => getWorkflow(accessToken!, orgId, workflowId),
    enabled: !!accessToken,
  });

  const versionsQuery = useQuery({
    queryKey: ["workflow-versions", orgId, workflowId, accessToken],
    queryFn: () => listVersions(accessToken!, orgId, workflowId),
    enabled: !!accessToken,
  });
  const currentVersion = versionsQuery.data?.[0]; // most recent first

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const runsQuery = useQuery({
    queryKey: ["workflow-runs", orgId, workflowId, accessToken],
    queryFn: () => listRuns(accessToken!, orgId, workflowId),
    enabled: !!accessToken,
    // Runs execute in the background worker (SPEC.md §22's execution
    // queue) -- poll while anything is in flight, same pattern as the
    // agent run history page.
    refetchInterval: (query) =>
      query.state.data?.some((run) => run.status === "pending" || run.status === "running")
        ? 2000
        : false,
  });

  const statusMutation = useMutation({
    mutationFn: (status: string) => updateWorkflowStatus(accessToken!, orgId, workflowId, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workflow", orgId, workflowId] }),
    onError: (err) => setActionError(err instanceof Error ? err.message : "failed to update status"),
  });

  const rotateMutation = useMutation({
    mutationFn: () => rotateWebhookSecret(accessToken!, orgId, workflowId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workflow", orgId, workflowId] }),
    onError: (err) => setActionError(err instanceof Error ? err.message : "failed to rotate secret"),
  });

  const versionMutation = useMutation({
    mutationFn: (graph: WorkflowGraph) => createVersion(accessToken!, orgId, workflowId, graph),
    onSuccess: () => {
      setEditingGraph(null);
      queryClient.invalidateQueries({ queryKey: ["workflow-versions", orgId, workflowId] });
    },
    onError: (err) => setActionError(err instanceof Error ? err.message : "failed to save version"),
  });

  const triggerMutation = useMutation({
    mutationFn: () => triggerRun(accessToken!, orgId, workflowId, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workflow-runs", orgId, workflowId] }),
    onError: (err) => setActionError(err instanceof Error ? err.message : "failed to trigger run"),
  });

  const canManage = permissionsQuery.data?.permissions.includes("workflows:manage") ?? false;
  const canRun = permissionsQuery.data?.permissions.includes("workflows:run") ?? false;
  const workflow = workflowQuery.data;
  const runs = runsQuery.data ?? [];
  const webhookUrl = `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/webhooks/workflows/${orgId}/${workflowId}`;

  if (workflowQuery.isLoading) return <Spinner label="Loading workflow…" />;
  if (workflowQuery.isError) {
    return (
      <Alert>
        {workflowQuery.error instanceof Error ? workflowQuery.error.message : "failed to load workflow"}
      </Alert>
    );
  }
  if (!workflow) return null;

  return (
    <>
      <div className="flex w-full max-w-2xl items-center justify-between">
        <h1 className="text-2xl font-semibold">{workflow.name}</h1>
        <span data-testid="workflow-detail-status" className="text-sm text-gray-500">
          {workflow.status}
        </span>
      </div>

      {canManage && (
        <div className="flex gap-2">
          {["draft", "active", "disabled"].map((status) => (
            <Button
              key={status}
              type="button"
              variant={workflow.status === status ? "primary" : "secondary"}
              onClick={() => statusMutation.mutate(status)}
              disabled={statusMutation.isPending}
              data-testid={`set-status-${status}`}
            >
              {status}
            </Button>
          ))}
        </div>
      )}

      {canRun && (
        <Button
          type="button"
          onClick={() => triggerMutation.mutate()}
          disabled={triggerMutation.isPending}
          data-testid="trigger-workflow-run"
        >
          {triggerMutation.isPending ? "Triggering…" : "Trigger run"}
        </Button>
      )}

      {canManage && (
        <div className="w-full max-w-2xl rounded border p-4 text-sm">
          <h2 className="font-medium">Webhook trigger</h2>
          <p className="mt-1 break-all text-gray-600">{webhookUrl}</p>
          <p className="mt-1 break-all text-gray-600" data-testid="webhook-secret">
            Secret: {workflow.webhook_secret}
          </p>
          <p className="mt-1 text-gray-500">Send it as the X-Webhook-Secret header.</p>
          <Button
            type="button"
            variant="secondary"
            onClick={() => rotateMutation.mutate()}
            disabled={rotateMutation.isPending}
            className="mt-2"
          >
            Rotate secret
          </Button>
        </div>
      )}

      {actionError && <Alert data-testid="workflow-action-error">{actionError}</Alert>}

      <h2 className="text-lg font-medium">Run history</h2>
      {runsQuery.isLoading && <Spinner label="Loading runs…" />}
      {runsQuery.isSuccess && runs.length === 0 && <EmptyState>No runs yet.</EmptyState>}
      <ul data-testid="run-list" className="flex w-full max-w-2xl flex-col gap-2">
        {runs.map((run) => (
          <li key={run.id} className="flex items-center justify-between gap-3">
            <Link
              href={`/orgs/${orgId}/workflows/${workflowId}/runs/${run.id}`}
              className="underline"
              data-testid={`run-link-${run.id}`}
            >
              {new Date(run.created_at).toLocaleString()}
            </Link>
            <span data-testid={`run-status-${run.id}`} className="text-sm text-gray-600">
              {run.status}
            </span>
          </li>
        ))}
      </ul>

      {canManage && (
        <div className="w-full max-w-2xl rounded border p-4">
          <h2 className="font-medium">
            {editingGraph ? "New version" : `Current version: v${currentVersion?.version ?? "?"}`}
          </h2>
          {editingGraph ? (
            <div className="mt-3 flex flex-col gap-3">
              <WorkflowGraphBuilder value={editingGraph} onChange={setEditingGraph} />
              <div className="flex gap-2">
                <Button
                  type="button"
                  onClick={() => versionMutation.mutate(editingGraph)}
                  disabled={versionMutation.isPending}
                  data-testid="save-version-submit"
                >
                  {versionMutation.isPending ? "Saving…" : "Save new version"}
                </Button>
                <Button type="button" variant="secondary" onClick={() => setEditingGraph(null)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            currentVersion && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => setEditingGraph(currentVersion.graph)}
                className="mt-2"
                data-testid="edit-graph"
              >
                Edit graph
              </Button>
            )
          )}
        </div>
      )}
    </>
  );
}
