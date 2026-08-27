"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Alert, Button, EmptyState, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { listInbox, markAllRead, markRead, type Notification } from "@/lib/notifications-api";

const EVENT_LABELS: Record<string, string> = {
  "notify.manual": "Notification",
  "connector.sync_failed": "Connector sync failed",
};

function eventLabel(eventType: string): string {
  return EVENT_LABELS[eventType] ?? eventType;
}

export default function NotificationsPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const queryClient = useQueryClient();

  // Accumulated pages of the keyset-paginated inbox -- "Load more" appends
  // rather than replaces, same shape as a live-inserting feed.
  const [cursors, setCursors] = useState<(string | null)[]>([null]);

  const inboxQuery = useQuery({
    queryKey: ["notifications", orgId, accessToken, cursors],
    queryFn: async () => {
      const pages = await Promise.all(
        cursors.map((cursor) => listInbox(accessToken!, orgId, cursor))
      );
      return pages;
    },
    enabled: !!accessToken,
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["notifications", orgId] });
  }

  const markReadMutation = useMutation({
    mutationFn: (notificationId: string) => markRead(accessToken!, orgId, notificationId),
    onSuccess: invalidate,
  });

  const markAllReadMutation = useMutation({
    mutationFn: () => markAllRead(accessToken!, orgId),
    onSuccess: invalidate,
  });

  const pages = inboxQuery.data ?? [];
  const notifications: Notification[] = pages.flatMap((page) => page.results);
  const lastPage = pages[pages.length - 1];
  const hasMore = !!lastPage?.next_cursor;
  const hasUnread = notifications.some((n) => n.read_at === null);

  return (
    <>
      <div className="flex w-full max-w-2xl items-center justify-between">
        <h1 className="text-2xl font-semibold">Notifications</h1>
        <div className="flex items-center gap-3">
          <Link href={`/orgs/${orgId}/notifications/preferences`} className="text-sm underline">
            Preferences
          </Link>
          <Button
            type="button"
            variant="secondary"
            onClick={() => markAllReadMutation.mutate()}
            disabled={!hasUnread || markAllReadMutation.isPending}
            data-testid="mark-all-read"
          >
            Mark all read
          </Button>
        </div>
      </div>

      {inboxQuery.isLoading && <Spinner label="Loading notifications…" />}
      {inboxQuery.isError && (
        <Alert>
          {inboxQuery.error instanceof Error
            ? inboxQuery.error.message
            : "failed to load notifications"}
        </Alert>
      )}
      {inboxQuery.isSuccess && notifications.length === 0 && (
        <EmptyState>No notifications yet.</EmptyState>
      )}

      <ul data-testid="notification-list" className="flex w-full max-w-2xl flex-col gap-2">
        {notifications.map((notification) => (
          <li
            key={notification.id}
            data-testid={`notification-${notification.id}`}
            className={`flex items-start justify-between gap-3 rounded border p-3 text-sm ${
              notification.read_at === null ? "border-blue-400 bg-blue-50" : ""
            }`}
          >
            <div>
              <p className="font-medium">
                {eventLabel(notification.event_type)}{" "}
                <span className="text-gray-500">
                  ({notification.channel === "in_app" ? "in-app" : notification.channel})
                </span>
              </p>
              <p className="text-gray-700">{notification.subject ?? notification.body}</p>
              {notification.subject && <p className="text-gray-600">{notification.body}</p>}
              <p className="text-xs text-gray-500">
                {new Date(notification.created_at).toLocaleString()}
              </p>
            </div>
            {notification.read_at === null && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => markReadMutation.mutate(notification.id)}
                disabled={markReadMutation.isPending}
                data-testid={`mark-read-${notification.id}`}
              >
                Mark read
              </Button>
            )}
          </li>
        ))}
      </ul>

      {hasMore && (
        <Button
          type="button"
          variant="secondary"
          onClick={() => setCursors((prev) => [...prev, lastPage!.next_cursor])}
          disabled={inboxQuery.isFetching}
          data-testid="load-more"
        >
          {inboxQuery.isFetching ? "Loading…" : "Load more"}
        </Button>
      )}
    </>
  );
}
