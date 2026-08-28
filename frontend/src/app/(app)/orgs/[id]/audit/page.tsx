"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Alert, Button, EmptyState, Input, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { listAuditLogs, type AuditLog } from "@/lib/audit-api";
import { getMyPermissions } from "@/lib/orgs-api";

export default function AuditPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [actionFilter, setActionFilter] = useState("");
  // Accumulated pages of the keyset-paginated log, same "Load more" shape
  // as the notifications inbox -- an audit log is a live-inserting stream.
  const [cursors, setCursors] = useState<(string | null)[]>([null]);

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });
  const canRead = permissionsQuery.data?.permissions.includes("audit:read") ?? false;

  const auditQuery = useQuery({
    queryKey: ["audit", orgId, accessToken, actionFilter, cursors],
    queryFn: async () => {
      const pages = await Promise.all(
        cursors.map((cursor) =>
          listAuditLogs(accessToken!, orgId, {
            cursor,
            action: actionFilter || undefined,
          })
        )
      );
      return pages;
    },
    enabled: !!accessToken && canRead,
  });

  function applyFilter(next: string) {
    setActionFilter(next);
    setCursors([null]);
  }

  if (permissionsQuery.isSuccess && !canRead) {
    return (
      <>
        <h1 className="text-2xl font-semibold">Audit Log</h1>
        <Alert>Only Owners and Admins can view the audit log.</Alert>
      </>
    );
  }

  const pages = auditQuery.data ?? [];
  const logs: AuditLog[] = pages.flatMap((page) => page.results);
  const lastPage = pages[pages.length - 1];
  const hasMore = !!lastPage?.next_cursor;

  return (
    <>
      <h1 className="text-2xl font-semibold">Audit Log</h1>

      <Input
        type="text"
        placeholder="Filter by action (e.g. auth.login)"
        value={actionFilter}
        onChange={(event) => applyFilter(event.target.value)}
        className="w-full max-w-md"
        data-testid="audit-action-filter"
      />

      {auditQuery.isLoading && <Spinner label="Loading audit log…" />}
      {auditQuery.isError && (
        <Alert>
          {auditQuery.error instanceof Error ? auditQuery.error.message : "failed to load audit log"}
        </Alert>
      )}
      {auditQuery.isSuccess && logs.length === 0 && <EmptyState>No audit events yet.</EmptyState>}

      <ul data-testid="audit-list" className="flex w-full max-w-2xl flex-col gap-2">
        {logs.map((log) => (
          <li key={log.id} className="rounded border p-3 text-sm">
            <p className="font-medium">
              {log.action}
              {log.resource_type && <span className="text-gray-500"> ({log.resource_type})</span>}
            </p>
            <p className="text-gray-600">
              {log.actor_email ?? "system"} — {new Date(log.created_at).toLocaleString()}
            </p>
            {Object.keys(log.metadata).length > 0 && (
              <p className="text-xs text-gray-500">{JSON.stringify(log.metadata)}</p>
            )}
          </li>
        ))}
      </ul>

      {hasMore && (
        <Button
          type="button"
          variant="secondary"
          onClick={() => setCursors((prev) => [...prev, lastPage!.next_cursor])}
          disabled={auditQuery.isFetching}
          data-testid="load-more"
        >
          {auditQuery.isFetching ? "Loading…" : "Load more"}
        </Button>
      )}
    </>
  );
}
