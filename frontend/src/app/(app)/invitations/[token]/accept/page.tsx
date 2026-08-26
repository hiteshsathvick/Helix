"use client";

import { useMutation } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { Alert, Button } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { acceptInvitation } from "@/lib/orgs-api";

export default function AcceptInvitationPage() {
  const { accessToken, user, applySession } = useAuth();
  const params = useParams<{ token: string }>();
  const router = useRouter();

  const acceptMutation = useMutation({
    mutationFn: () => acceptInvitation(accessToken!, params.token),
    onSuccess: (response) => {
      applySession(response);
      router.push("/account");
    },
  });

  return (
    <>
      <h1 className="text-2xl font-semibold">Join organization</h1>
      <p className="text-center">
        You&apos;re signed in as <strong>{user?.email}</strong>. Accepting this invite must
        match the email it was sent to.
      </p>
      {acceptMutation.isError && (
        <Alert data-testid="accept-invite-error">
          {acceptMutation.error instanceof Error
            ? acceptMutation.error.message
            : "failed to accept invitation"}
        </Alert>
      )}
      <Button onClick={() => acceptMutation.mutate()} disabled={acceptMutation.isPending}>
        {acceptMutation.isPending ? "Joining…" : "Accept invitation"}
      </Button>
    </>
  );
}
