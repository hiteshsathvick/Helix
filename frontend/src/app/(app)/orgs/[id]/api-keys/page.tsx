"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, EmptyState, Input, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { AVAILABLE_SCOPES, createApiKey, listApiKeys, revokeApiKey } from "@/lib/api-keys-api";
import { getMyPermissions } from "@/lib/orgs-api";

export default function ApiKeysPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [rawKey, setRawKey] = useState<string | null>(null);

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });
  const canManage = permissionsQuery.data?.permissions.includes("api_keys:manage") ?? false;

  const keysQuery = useQuery({
    queryKey: ["api-keys", orgId, accessToken],
    queryFn: () => listApiKeys(accessToken!, orgId),
    enabled: !!accessToken && canManage,
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["api-keys", orgId] });
  }

  const createMutation = useMutation({
    mutationFn: () => createApiKey(accessToken!, orgId, name, scopes),
    onSuccess: (created) => {
      setRawKey(created.raw_key);
      setName("");
      setScopes([]);
      invalidate();
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (keyId: string) => revokeApiKey(accessToken!, orgId, keyId),
    onSuccess: invalidate,
  });

  function toggleScope(scope: string) {
    setScopes((prev) => (prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || scopes.length === 0) return;
    createMutation.mutate();
  }

  if (permissionsQuery.isSuccess && !canManage) {
    return (
      <>
        <h1 className="text-2xl font-semibold">API Keys</h1>
        <Alert>Only Owners and Admins can manage API keys.</Alert>
      </>
    );
  }

  const keys = keysQuery.data ?? [];

  return (
    <>
      <h1 className="text-2xl font-semibold">API Keys</h1>

      {rawKey && (
        <Alert variant="success" data-testid="raw-key-banner">
          Save this key now — it won&apos;t be shown again:{" "}
          <code className="break-all">{rawKey}</code>
        </Alert>
      )}

      {keysQuery.isLoading && <Spinner label="Loading keys…" />}
      {keysQuery.isSuccess && keys.length === 0 && <EmptyState>No API keys yet.</EmptyState>}

      <ul data-testid="api-key-list" className="flex w-full max-w-2xl flex-col gap-2">
        {keys.map((key) => (
          <li key={key.id} className="flex items-center justify-between rounded border p-3 text-sm">
            <div>
              <p className="font-medium">
                {key.name} <span className="text-gray-500">({key.prefix}…)</span>
              </p>
              <p className="text-gray-600">{key.scopes.join(", ")}</p>
              <p className="text-xs text-gray-500">
                {key.last_used_at
                  ? `Last used ${new Date(key.last_used_at).toLocaleString()}`
                  : "Never used"}
              </p>
            </div>
            <Button
              type="button"
              variant="danger"
              onClick={() => revokeMutation.mutate(key.id)}
              disabled={revokeMutation.isPending}
              data-testid={`revoke-${key.id}`}
            >
              Revoke
            </Button>
          </li>
        ))}
      </ul>

      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-3">
        <Input
          type="text"
          placeholder="Key name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          data-testid="key-name-input"
        />
        <div className="flex flex-col gap-1 text-sm">
          {AVAILABLE_SCOPES.map((scope) => (
            <label key={scope} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={scopes.includes(scope)}
                onChange={() => toggleScope(scope)}
                data-testid={`scope-${scope}`}
              />
              {scope}
            </label>
          ))}
        </div>
        {createMutation.isError && (
          <Alert data-testid="create-key-error">
            {createMutation.error instanceof Error
              ? createMutation.error.message
              : "failed to create key"}
          </Alert>
        )}
        <Button type="submit" disabled={createMutation.isPending} data-testid="create-key-submit">
          {createMutation.isPending ? "Creating…" : "Create key"}
        </Button>
      </form>
    </>
  );
}
