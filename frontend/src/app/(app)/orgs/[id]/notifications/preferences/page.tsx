"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Alert, Button, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { getPrefs, updatePrefs, type NotificationPref } from "@/lib/notifications-api";

const EVENT_LABELS: Record<string, string> = {
  "notify.manual": "Notification",
  "connector.sync_failed": "Connector sync failed",
};

const CHANNEL_LABELS: Record<string, string> = { email: "Email", in_app: "In-app" };

function eventLabel(event: string): string {
  return EVENT_LABELS[event] ?? event;
}

export default function NotificationPreferencesPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const queryClient = useQueryClient();

  const prefsQuery = useQuery({
    queryKey: ["notification-prefs", orgId, accessToken],
    queryFn: () => getPrefs(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const updateMutation = useMutation({
    mutationFn: (prefs: NotificationPref[]) => updatePrefs(accessToken!, orgId, prefs),
    onSuccess: (updated) => {
      queryClient.setQueryData(["notification-prefs", orgId, accessToken], updated);
    },
  });

  const prefs = prefsQuery.data ?? [];
  // Rows grouped by event -- each event has one row with an email + in-app
  // toggle, and email additionally gets an immediate/digest choice (in-app
  // is always immediate; see notifications/service.py::notify).
  const events = Array.from(new Set(prefs.map((p) => p.event)));

  function prefFor(event: string, channel: "email" | "in_app"): NotificationPref | undefined {
    return prefs.find((p) => p.event === event && p.channel === channel);
  }

  function save(next: NotificationPref) {
    const others = prefs.filter((p) => !(p.event === next.event && p.channel === next.channel));
    updateMutation.mutate([...others, next].map(({ channel, event, enabled, frequency }) => ({
      channel,
      event,
      enabled,
      frequency,
    })));
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">Notification preferences</h1>

      {prefsQuery.isLoading && <Spinner label="Loading preferences…" />}
      {prefsQuery.isError && (
        <Alert>
          {prefsQuery.error instanceof Error
            ? prefsQuery.error.message
            : "failed to load preferences"}
        </Alert>
      )}
      {updateMutation.isError && (
        <Alert data-testid="prefs-error">
          {updateMutation.error instanceof Error
            ? updateMutation.error.message
            : "failed to update preferences"}
        </Alert>
      )}

      {prefsQuery.isSuccess && (
        <div className="w-full max-w-2xl overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="py-2">Event</th>
                <th className="py-2">Email</th>
                <th className="py-2">Frequency</th>
                <th className="py-2">In-app</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const email = prefFor(event, "email");
                const inApp = prefFor(event, "in_app");
                return (
                  <tr key={event} className="border-b">
                    <td className="py-2">{eventLabel(event)}</td>
                    <td className="py-2">
                      <input
                        type="checkbox"
                        checked={email?.enabled ?? true}
                        disabled={!email || updateMutation.isPending}
                        data-testid={`pref-email-enabled-${event}`}
                        onChange={(e) =>
                          email && save({ ...email, enabled: e.target.checked })
                        }
                      />
                      <span className="sr-only">{CHANNEL_LABELS.email}</span>
                    </td>
                    <td className="py-2">
                      <select
                        className="rounded border px-2 py-1"
                        value={email?.frequency ?? "immediate"}
                        disabled={!email || !email.enabled || updateMutation.isPending}
                        data-testid={`pref-email-frequency-${event}`}
                        onChange={(e) =>
                          email &&
                          save({
                            ...email,
                            frequency: e.target.value as "immediate" | "digest",
                          })
                        }
                      >
                        <option value="immediate">Immediate</option>
                        <option value="digest">Daily digest</option>
                      </select>
                    </td>
                    <td className="py-2">
                      <input
                        type="checkbox"
                        checked={inApp?.enabled ?? true}
                        disabled={!inApp || updateMutation.isPending}
                        data-testid={`pref-in_app-enabled-${event}`}
                        onChange={(e) =>
                          inApp && save({ ...inApp, enabled: e.target.checked })
                        }
                      />
                      <span className="sr-only">{CHANNEL_LABELS.in_app}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
