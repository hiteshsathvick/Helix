"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/lib/auth-context";
import { acceptInvitation } from "@/lib/orgs-api";

function AcceptInvitationContent() {
  const { accessToken, user, applySession } = useAuth();
  const params = useParams<{ token: string }>();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleAccept() {
    if (!accessToken) return;
    setError(null);
    setSubmitting(true);
    try {
      const response = await acceptInvitation(accessToken, params.token);
      applySession(response);
      router.push("/account");
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to accept invitation");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-24 text-center">
      <h1 className="text-2xl font-semibold">Join organization</h1>
      <p>
        You&apos;re signed in as <strong>{user?.email}</strong>. Accepting this invite must
        match the email it was sent to.
      </p>
      {error && (
        <p data-testid="accept-invite-error" className="text-red-600">
          {error}
        </p>
      )}
      <button
        onClick={handleAccept}
        disabled={submitting}
        className="rounded bg-black px-3 py-2 text-white disabled:opacity-50"
      >
        {submitting ? "Joining…" : "Accept invitation"}
      </button>
    </main>
  );
}

export default function AcceptInvitationPage() {
  return (
    <ProtectedRoute>
      <AcceptInvitationContent />
    </ProtectedRoute>
  );
}
