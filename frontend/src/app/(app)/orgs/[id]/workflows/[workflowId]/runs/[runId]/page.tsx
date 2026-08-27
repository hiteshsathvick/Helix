"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Alert, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { getRun } from "@/lib/workflows-api";

export default function WorkflowRunPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string; workflowId: string; runId: string }>();
  const { id: orgId, workflowId, runId } = params;

  const runQuery = useQuery({
    queryKey: ["workflow-run", orgId, workflowId, runId, accessToken],
    queryFn: () => getRun(accessToken!, orgId, workflowId, runId),
    enabled: !!accessToken,
    refetchInterval: (query) =>
      query.state.data?.status === "pending" || query.state.data?.status === "running"
        ? 2000
        : false,
  });

  if (runQuery.isLoading) return <Spinner label="Loading run…" />;
  if (runQuery.isError) {
    return (
      <Alert>{runQuery.error instanceof Error ? runQuery.error.message : "failed to load run"}</Alert>
    );
  }

  const run = runQuery.data;
  if (!run) return null;

  return (
    <>
      <h1 className="text-2xl font-semibold">Run</h1>

      <dl className="grid w-full max-w-2xl grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-gray-500">Status</dt>
        <dd data-testid="run-detail-status">{run.status}</dd>
        <dt className="text-gray-500">Trigger</dt>
        <dd>{JSON.stringify(run.trigger)}</dd>
        {run.error && (
          <>
            <dt className="text-gray-500">Error</dt>
            <dd data-testid="run-detail-error" className="text-red-600">
              {run.error}
            </dd>
          </>
        )}
        <dt className="text-gray-500">Cost</dt>
        <dd>${run.cost.toFixed(4)}</dd>
      </dl>

      <h2 className="text-lg font-medium">Steps</h2>
      <ol data-testid="run-steps" className="flex w-full max-w-2xl flex-col gap-3">
        {run.steps.map((step) => (
          <li
            key={step.id}
            className="rounded border p-3 text-sm"
            data-testid={`step-${step.node_id}`}
          >
            <p className="font-medium">
              {step.node_id} — {step.node_type}
              <span className="ml-2 text-gray-500">
                ({step.status}, {step.attempts} attempt{step.attempts === 1 ? "" : "s"})
              </span>
            </p>
            <p className="mt-1 text-gray-600">Input: {JSON.stringify(step.input)}</p>
            <p className="text-gray-600">Output: {JSON.stringify(step.output)}</p>
            {step.error && (
              <p className="text-red-600" data-testid={`step-error-${step.node_id}`}>
                Error: {step.error}
              </p>
            )}
          </li>
        ))}
      </ol>
    </>
  );
}
