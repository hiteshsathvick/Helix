"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, EmptyState, Input, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { getMyPermissions } from "@/lib/orgs-api";
import {
  createWebhook,
  deactivateWebhook,
  listDeliveries,
  listWebhooks,
  type Webhook,
} from "@/lib/webhooks-api";

function DeliveriesPanel({ orgId, webhookId }: { orgId: string; webhookId: string }) {
  const { accessToken } = useAuth();
  const deliveriesQuery = useQuery({
    queryKey: ["webhook-deliveries", orgId, webhookId, accessToken],
    queryFn: () => listDeliveries(accessToken!, orgId, webhookId),
    enabled: !!accessToken,
  });
  const deliveries = deliveriesQuery.data ?? [];

  if (deliveriesQuery.isLoading) return <Spinner label="Loading deliveries…" />;
  if (deliveries.length === 0) return <p className="text-xs text-gray-500">No deliveries yet.</p>;

  return (
    <ul className="text-xs text-gray-600">
      {deliveries.map((delivery) => (
        <li key={delivery.id}>
          {delivery.event_type} — {delivery.status}
          {delivery.response_status !== null && ` (HTTP ${delivery.response_status})`} — attempt
          {delivery.attempts !== 1 ? "s" : ""} {delivery.attempts}
        </li>
      ))}
    </ul>
  );
}

export default function WebhooksPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const queryClient = useQueryClient();

  const [url, setUrl] = useState("");
  const [eventsText, setEventsText] = useState("document.ingested");
  const [secret, setSecret] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });
  const canManage = permissionsQuery.data?.permissions.includes("webhooks:manage") ?? false;

  const webhooksQuery = useQuery({
    queryKey: ["webhooks", orgId, accessToken],
    queryFn: () => listWebhooks(accessToken!, orgId),
    enabled: !!accessToken && canManage,
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["webhooks", orgId] });
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createWebhook(
        accessToken!,
        orgId,
        url,
        eventsText
          .split(",")
          .map((e) => e.trim())
          .filter(Boolean)
      ),
    onSuccess: (created) => {
      setSecret(created.secret);
      setUrl("");
      invalidate();
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: (webhookId: string) => deactivateWebhook(accessToken!, orgId, webhookId),
    onSuccess: invalidate,
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!url.trim() || !eventsText.trim()) return;
    createMutation.mutate();
  }

  if (permissionsQuery.isSuccess && !canManage) {
    return (
      <>
        <h1 className="text-2xl font-semibold">Webhooks</h1>
        <Alert>Only Owners and Admins can manage webhooks.</Alert>
      </>
    );
  }

  const webhooks: Webhook[] = webhooksQuery.data ?? [];

  return (
    <>
      <h1 className="text-2xl font-semibold">Webhooks</h1>

      {secret && (
        <Alert variant="success" data-testid="webhook-secret-banner">
          Save this signing secret now — it won&apos;t be shown again:{" "}
          <code className="break-all">{secret}</code>
        </Alert>
      )}

      {webhooksQuery.isLoading && <Spinner label="Loading webhooks…" />}
      {webhooksQuery.isSuccess && webhooks.length === 0 && <EmptyState>No webhooks yet.</EmptyState>}

      <ul data-testid="webhook-list" className="flex w-full max-w-2xl flex-col gap-2">
        {webhooks.map((webhook) => (
          <li key={webhook.id} className="rounded border p-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-medium break-all">{webhook.url}</p>
                <p className="text-gray-600">
                  {webhook.events.join(", ")} — {webhook.active ? "active" : "inactive"}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setExpandedId(expandedId === webhook.id ? null : webhook.id)}
                >
                  {expandedId === webhook.id ? "Hide deliveries" : "View deliveries"}
                </Button>
                {webhook.active && (
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() => deactivateMutation.mutate(webhook.id)}
                    disabled={deactivateMutation.isPending}
                    data-testid={`deactivate-${webhook.id}`}
                  >
                    Deactivate
                  </Button>
                )}
              </div>
            </div>
            {expandedId === webhook.id && (
              <div className="mt-2 border-t pt-2">
                <DeliveriesPanel orgId={orgId} webhookId={webhook.id} />
              </div>
            )}
          </li>
        ))}
      </ul>

      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-3">
        <Input
          type="text"
          placeholder="https://your-app.example.com/webhooks/helix"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          data-testid="webhook-url-input"
        />
        <Input
          type="text"
          placeholder="Events (comma-separated), e.g. document.ingested"
          value={eventsText}
          onChange={(event) => setEventsText(event.target.value)}
          data-testid="webhook-events-input"
        />
        {createMutation.isError && (
          <Alert data-testid="create-webhook-error">
            {createMutation.error instanceof Error
              ? createMutation.error.message
              : "failed to create webhook"}
          </Alert>
        )}
        <Button
          type="submit"
          disabled={createMutation.isPending}
          data-testid="create-webhook-submit"
        >
          {createMutation.isPending ? "Creating…" : "Add webhook"}
        </Button>
      </form>
    </>
  );
}
