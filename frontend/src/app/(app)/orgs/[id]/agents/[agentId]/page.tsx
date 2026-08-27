"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, EmptyState, Input, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { listAgents, listRuns, triggerRun } from "@/lib/agents-api";
import { getMyPermissions } from "@/lib/orgs-api";

export default function AgentDetailPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string; agentId: string }>();
  const orgId = params.id;
  const agentId = params.agentId;
  const queryClient = useQueryClient();

  const [input, setInput] = useState("");
  const [triggerError, setTriggerError] = useState<string | null>(null);

  // No single-agent GET endpoint (Phase 12 only lists) — filtering the list
  // client-side avoids adding one just for this page's header.
  const agentsQuery = useQuery({
    queryKey: ["agents", orgId, accessToken],
    queryFn: () => listAgents(accessToken!, orgId),
    enabled: !!accessToken,
  });
  const agent = agentsQuery.data?.find((a) => a.id === agentId);

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const runsQuery = useQuery({
    queryKey: ["agent-runs", orgId, agentId, accessToken],
    queryFn: () => listRuns(accessToken!, orgId, agentId),
    enabled: !!accessToken,
    // A run executes in the background (Phase 12: SPEC.md §22's execution
    // queue, not inline) — poll while anything is still in flight so
    // status reflects real progress without a manual reload.
    refetchInterval: (query) =>
      query.state.data?.some((run) => run.status === "pending" || run.status === "running")
        ? 2000
        : false,
  });

  const triggerMutation = useMutation({
    mutationFn: () => triggerRun(accessToken!, orgId, agentId, input),
    onSuccess: () => {
      setInput("");
      queryClient.invalidateQueries({ queryKey: ["agent-runs", orgId, agentId] });
    },
    onError: (err) =>
      setTriggerError(err instanceof Error ? err.message : "failed to trigger run"),
  });

  const canRun = permissionsQuery.data?.permissions.includes("agents:run") ?? false;
  const runs = runsQuery.data ?? [];

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setTriggerError(null);
    if (!input.trim()) return;
    triggerMutation.mutate();
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">{agent?.name ?? "Agent"}</h1>
      {agent && <p className="max-w-md text-sm text-gray-600">{agent.instructions}</p>}

      {canRun && (
        <form onSubmit={handleSubmit} className="flex w-full max-w-md gap-2">
          <Input
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="What should this run do?"
            data-testid="run-input"
            className="flex-1"
            disabled={triggerMutation.isPending}
          />
          <Button type="submit" disabled={triggerMutation.isPending || !input.trim()}>
            Run
          </Button>
        </form>
      )}
      {triggerError && <Alert data-testid="trigger-error">{triggerError}</Alert>}

      <h2 className="text-lg font-medium">Run history</h2>
      {runsQuery.isLoading && <Spinner label="Loading runs…" />}
      {runsQuery.isSuccess && runs.length === 0 && <EmptyState>No runs yet.</EmptyState>}
      <ul data-testid="run-list" className="flex w-full max-w-md flex-col gap-2">
        {runs.map((run) => (
          <li key={run.id} className="flex items-center justify-between gap-3">
            <Link
              href={`/orgs/${orgId}/agents/${agentId}/runs/${run.id}`}
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
    </>
  );
}
