"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Alert, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { getAnalyticsOverview } from "@/lib/analytics-api";
import { getMyPermissions } from "@/lib/orgs-api";

function StatusCounts({ title, counts }: { title: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  return (
    <div className="rounded border p-4">
      <h2 className="font-medium">{title}</h2>
      {entries.length === 0 ? (
        <p className="text-sm text-gray-500">No data yet.</p>
      ) : (
        <ul className="text-sm">
          {entries.map(([status, count]) => (
            <li key={status}>
              {status}: {count}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function AnalyticsPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });
  const canRead = permissionsQuery.data?.permissions.includes("analytics:read") ?? false;

  const overviewQuery = useQuery({
    queryKey: ["analytics-overview", orgId, accessToken],
    queryFn: () => getAnalyticsOverview(accessToken!, orgId),
    enabled: !!accessToken && canRead,
  });

  if (permissionsQuery.isSuccess && !canRead) {
    return (
      <>
        <h1 className="text-2xl font-semibold">Analytics</h1>
        <Alert>Only Owners and Admins can view analytics.</Alert>
      </>
    );
  }

  const overview = overviewQuery.data;

  return (
    <>
      <h1 className="text-2xl font-semibold">Analytics{overview ? ` (${overview.month})` : ""}</h1>

      {overviewQuery.isLoading && <Spinner label="Loading analytics…" />}
      {overviewQuery.isError && (
        <Alert>
          {overviewQuery.error instanceof Error
            ? overviewQuery.error.message
            : "failed to load analytics"}
        </Alert>
      )}

      {overview && (
        <div className="grid w-full max-w-3xl grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="rounded border p-4">
            <h2 className="font-medium">Usage</h2>
            <p className="text-sm">
              Total cost: ${overview.usage.total_cost_usd.toFixed(4)}
              {overview.usage.monthly_cost_cap_usd !== null &&
                ` / $${overview.usage.monthly_cost_cap_usd.toFixed(2)} cap`}
            </p>
            <ul className="text-sm">
              {overview.usage.items.map((item) => (
                <li key={item.kind}>
                  {item.kind}: {item.quantity} tokens (${item.cost_usd.toFixed(4)})
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded border p-4">
            <h2 className="font-medium">Active users</h2>
            <p className="text-2xl" data-testid="active-users">
              {overview.active_users}
            </p>
          </div>

          <StatusCounts title="Agent runs" counts={overview.agent_runs_by_status} />
          <StatusCounts title="Workflow runs" counts={overview.workflow_runs_by_status} />
          <StatusCounts title="Document ingestion health" counts={overview.documents_by_status} />
        </div>
      )}
    </>
  );
}
