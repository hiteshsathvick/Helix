"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Alert, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { getRun } from "@/lib/agents-api";

export default function AgentRunPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string; agentId: string; runId: string }>();
  const { id: orgId, agentId, runId } = params;

  const runQuery = useQuery({
    queryKey: ["agent-run", orgId, agentId, runId, accessToken],
    queryFn: () => getRun(accessToken!, orgId, agentId, runId),
    enabled: !!accessToken,
    refetchInterval: (query) =>
      query.state.data?.status === "pending" || query.state.data?.status === "running"
        ? 2000
        : false,
  });

  if (runQuery.isLoading) return <Spinner label="Loading run…" />;
  if (runQuery.isError) {
    return (
      <Alert>
        {runQuery.error instanceof Error ? runQuery.error.message : "failed to load run"}
      </Alert>
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
        <dt className="text-gray-500">Input</dt>
        <dd>{run.input}</dd>
        {run.output && (
          <>
            <dt className="text-gray-500">Output</dt>
            <dd data-testid="run-detail-output">{run.output}</dd>
          </>
        )}
        {run.error && (
          <>
            <dt className="text-gray-500">Error</dt>
            <dd data-testid="run-detail-error" className="text-red-600">
              {run.error}
            </dd>
          </>
        )}
        <dt className="text-gray-500">Tokens</dt>
        <dd>{run.tokens}</dd>
        <dt className="text-gray-500">Cost</dt>
        <dd>${run.cost.toFixed(4)}</dd>
      </dl>

      <h2 className="text-lg font-medium">Steps</h2>
      <ol data-testid="run-steps" className="flex w-full max-w-2xl flex-col gap-3">
        {run.steps.map((step) => (
          <li key={step.id} className="rounded border p-3 text-sm" data-testid={`step-${step.ordinal}`}>
            <p className="font-medium">
              #{step.ordinal} — {step.type}
              {step.tool && ` (${step.tool})`}
            </p>
            {step.type === "tool_call" && (
              <>
                <p className="mt-1 text-gray-600">Input: {JSON.stringify(step.input)}</p>
                <p className="text-gray-600">Output: {JSON.stringify(step.output)}</p>
              </>
            )}
            {step.type === "final_answer" && (
              <p className="mt-1 text-gray-600">{String(step.output.text ?? "")}</p>
            )}
          </li>
        ))}
      </ol>
    </>
  );
}
