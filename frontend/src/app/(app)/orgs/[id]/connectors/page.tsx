"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, EmptyState, Input, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import {
  createWebConnector,
  disconnectConnector,
  listConnectors,
  startGitHubAuthorize,
  triggerSync,
} from "@/lib/connectors-api";
import { getMyPermissions } from "@/lib/orgs-api";

export default function ConnectorsPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const queryClient = useQueryClient();

  const [webName, setWebName] = useState("");
  const [urlListText, setUrlListText] = useState("");
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("main");
  const [formError, setFormError] = useState<string | null>(null);

  const connectorsQuery = useQuery({
    queryKey: ["connectors", orgId, accessToken],
    queryFn: () => listConnectors(accessToken!, orgId),
    enabled: !!accessToken,
    // A sync runs in the background worker -- poll while anything is
    // mid-sync, same refetchInterval pattern as documents/agents/workflows.
    refetchInterval: (query) =>
      query.state.data?.some((connector) => connector.status === "syncing") ? 3000 : false,
  });

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });

  function invalidateConnectors() {
    queryClient.invalidateQueries({ queryKey: ["connectors", orgId] });
  }

  const createWebMutation = useMutation({
    mutationFn: () =>
      createWebConnector(
        accessToken!,
        orgId,
        webName,
        urlListText
          .split("\n")
          .map((url) => url.trim())
          .filter(Boolean)
      ),
    onSuccess: () => {
      setWebName("");
      setUrlListText("");
      invalidateConnectors();
    },
    onError: (err) =>
      setFormError(err instanceof Error ? err.message : "failed to create connector"),
  });

  const githubConnectMutation = useMutation({
    mutationFn: () => startGitHubAuthorize(accessToken!, orgId, repo, branch),
    onSuccess: (authorizeUrl) => {
      window.location.href = authorizeUrl;
    },
    onError: (err) =>
      setFormError(err instanceof Error ? err.message : "failed to start GitHub connect"),
  });

  const syncMutation = useMutation({
    mutationFn: (connectorId: string) => triggerSync(accessToken!, orgId, connectorId),
    onSuccess: invalidateConnectors,
  });

  const disconnectMutation = useMutation({
    mutationFn: (connectorId: string) => disconnectConnector(accessToken!, orgId, connectorId),
    onSuccess: invalidateConnectors,
  });

  const canManage = permissionsQuery.data?.permissions.includes("connectors:manage") ?? false;
  const connectors = connectorsQuery.data ?? [];

  function handleWebSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    if (!webName.trim() || !urlListText.trim()) return;
    createWebMutation.mutate();
  }

  function handleGitHubSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    if (!repo.trim()) return;
    githubConnectMutation.mutate();
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">Connectors</h1>

      {connectorsQuery.isLoading && <Spinner label="Loading connectors…" />}
      {connectorsQuery.isError && (
        <Alert>
          {connectorsQuery.error instanceof Error
            ? connectorsQuery.error.message
            : "failed to load connectors"}
        </Alert>
      )}
      {connectorsQuery.isSuccess && connectors.length === 0 && (
        <EmptyState>No connectors yet.</EmptyState>
      )}

      <ul data-testid="connector-list" className="flex w-full max-w-2xl flex-col gap-2">
        {connectors.map((connector) => (
          <li
            key={connector.id}
            className="flex items-center justify-between gap-3 rounded border p-3 text-sm"
          >
            <div>
              <p className="font-medium">
                {connector.name} <span className="text-gray-500">({connector.type})</span>
              </p>
              <p data-testid={`connector-status-${connector.id}`} className="text-gray-600">
                {connector.status}
                {connector.last_synced_at &&
                  ` — last synced ${new Date(connector.last_synced_at).toLocaleString()}`}
              </p>
              {connector.last_sync_error && (
                <p className="text-red-600" data-testid={`connector-error-${connector.id}`}>
                  {connector.last_sync_error}
                </p>
              )}
            </div>
            {canManage && (
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => syncMutation.mutate(connector.id)}
                  disabled={connector.status === "syncing" || syncMutation.isPending}
                  data-testid={`sync-connector-${connector.id}`}
                >
                  Sync now
                </Button>
                <Button
                  type="button"
                  variant="danger"
                  onClick={() => disconnectMutation.mutate(connector.id)}
                  disabled={disconnectMutation.isPending}
                >
                  Disconnect
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>

      {formError && <Alert data-testid="connector-form-error">{formError}</Alert>}

      {canManage && (
        <div className="flex w-full max-w-2xl flex-col gap-6">
          <form
            onSubmit={handleWebSubmit}
            className="flex flex-col gap-3 rounded border p-4"
          >
            <h2 className="font-medium">Connect a website</h2>
            <Input
              type="text"
              placeholder="Name"
              value={webName}
              onChange={(event) => setWebName(event.target.value)}
              data-testid="web-connector-name-input"
            />
            <textarea
              placeholder="One URL per line"
              value={urlListText}
              onChange={(event) => setUrlListText(event.target.value)}
              data-testid="web-connector-urls-input"
              className="rounded border px-3 py-2"
              rows={4}
            />
            <Button
              type="submit"
              disabled={createWebMutation.isPending}
              data-testid="create-web-connector-submit"
            >
              {createWebMutation.isPending ? "Creating…" : "Connect"}
            </Button>
          </form>

          <form
            onSubmit={handleGitHubSubmit}
            className="flex flex-col gap-3 rounded border p-4"
          >
            <h2 className="font-medium">Connect a GitHub repository</h2>
            <Input
              type="text"
              placeholder="owner/repo"
              value={repo}
              onChange={(event) => setRepo(event.target.value)}
              data-testid="github-repo-input"
            />
            <Input
              type="text"
              placeholder="Branch"
              value={branch}
              onChange={(event) => setBranch(event.target.value)}
              data-testid="github-branch-input"
            />
            <Button
              type="submit"
              disabled={githubConnectMutation.isPending}
              data-testid="github-connect-submit"
            >
              Connect with GitHub
            </Button>
          </form>
        </div>
      )}
    </>
  );
}
