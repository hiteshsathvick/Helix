"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, EmptyState, Input, Spinner } from "@/components/ui";
import { WorkflowGraphBuilder } from "@/components/WorkflowGraphBuilder";
import { useAuth } from "@/lib/auth-context";
import { getMyPermissions } from "@/lib/orgs-api";
import { createWorkflow, listWorkflows, type WorkflowGraph } from "@/lib/workflows-api";

const EMPTY_GRAPH: WorkflowGraph = {
  nodes: [{ id: "start", type: "trigger", config: {} }],
  edges: [],
};

export default function WorkflowsPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [graph, setGraph] = useState<WorkflowGraph>(EMPTY_GRAPH);
  const [formError, setFormError] = useState<string | null>(null);

  const workflowsQuery = useQuery({
    queryKey: ["workflows", orgId, accessToken],
    queryFn: () => listWorkflows(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const createMutation = useMutation({
    mutationFn: () => createWorkflow(accessToken!, orgId, name, graph),
    onSuccess: () => {
      setName("");
      setGraph(EMPTY_GRAPH);
      queryClient.invalidateQueries({ queryKey: ["workflows", orgId] });
    },
    onError: (err) =>
      setFormError(err instanceof Error ? err.message : "failed to create workflow"),
  });

  const canManage = permissionsQuery.data?.permissions.includes("workflows:manage") ?? false;
  const workflows = workflowsQuery.data ?? [];

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    if (!name.trim() || graph.nodes.length === 0) return;
    createMutation.mutate();
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">Workflows</h1>

      {workflowsQuery.isLoading && <Spinner label="Loading workflows…" />}
      {workflowsQuery.isError && (
        <Alert>
          {workflowsQuery.error instanceof Error
            ? workflowsQuery.error.message
            : "failed to load workflows"}
        </Alert>
      )}
      {workflowsQuery.isSuccess && workflows.length === 0 && (
        <EmptyState>No workflows yet.</EmptyState>
      )}

      <ul data-testid="workflow-list" className="flex w-full max-w-md flex-col gap-2">
        {workflows.map((workflow) => (
          <li key={workflow.id} className="flex items-center justify-between gap-3">
            <Link
              href={`/orgs/${orgId}/workflows/${workflow.id}`}
              className="underline"
              data-testid={`workflow-link-${workflow.id}`}
            >
              {workflow.name}
            </Link>
            <span data-testid={`workflow-status-${workflow.id}`} className="text-sm text-gray-500">
              {workflow.status}
            </span>
          </li>
        ))}
      </ul>

      {canManage && (
        <form
          onSubmit={handleSubmit}
          className="flex w-full max-w-2xl flex-col gap-3 rounded border p-4"
        >
          <h2 className="font-medium">New workflow</h2>
          <Input
            type="text"
            placeholder="Name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            data-testid="workflow-name-input"
          />
          <WorkflowGraphBuilder value={graph} onChange={setGraph} />
          <Button
            type="submit"
            disabled={createMutation.isPending}
            data-testid="create-workflow-submit"
          >
            {createMutation.isPending ? "Creating…" : "Create workflow"}
          </Button>
          {formError && <Alert data-testid="create-workflow-error">{formError}</Alert>}
        </form>
      )}
    </>
  );
}
