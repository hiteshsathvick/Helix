"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, EmptyState, Input, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { getMyPermissions, inviteMember, listMembers } from "@/lib/orgs-api";

export default function MembersPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const queryClient = useQueryClient();

  const [email, setEmail] = useState("");
  const [inviteLink, setInviteLink] = useState<string | null>(null);

  const membersQuery = useQuery({
    queryKey: ["members", orgId, accessToken],
    queryFn: () => listMembers(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const permissionsQuery = useQuery({
    queryKey: ["permissions", orgId, accessToken],
    queryFn: () => getMyPermissions(accessToken!, orgId),
    enabled: !!accessToken,
  });

  const inviteMutation = useMutation({
    mutationFn: () => inviteMember(accessToken!, orgId, email),
    onSuccess: ({ token }) => {
      setInviteLink(`${window.location.origin}/invitations/${token}/accept`);
      setEmail("");
      queryClient.invalidateQueries({ queryKey: ["members", orgId] });
    },
  });

  // The server is still authoritative (POST /invitations 403s regardless) —
  // this only decides what the UI shows, per CLAUDE.md's "hide/disable by
  // permission" frontend rule.
  const canInvite = permissionsQuery.data?.permissions.includes("members:invite") ?? false;
  const members = membersQuery.data ?? [];

  function handleInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken) return;
    inviteMutation.mutate();
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">Members</h1>

      {membersQuery.isLoading && <Spinner label="Loading members…" />}
      {membersQuery.isError && (
        <Alert>
          {membersQuery.error instanceof Error ? membersQuery.error.message : "failed to load members"}
        </Alert>
      )}
      {membersQuery.isSuccess && members.length === 0 && <EmptyState>No members yet.</EmptyState>}
      <ul data-testid="member-list" className="flex flex-col gap-1">
        {members.map((member) => (
          <li key={member.id}>
            {member.email} — {member.role_name} ({member.status})
          </li>
        ))}
      </ul>

      {canInvite && (
        <form onSubmit={handleInvite} className="flex w-full max-w-sm flex-col gap-3">
          <Input
            type="email"
            placeholder="Invite by email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
          {inviteMutation.isError && (
            <Alert data-testid="invite-error">
              {inviteMutation.error instanceof Error
                ? inviteMutation.error.message
                : "failed to invite member"}
            </Alert>
          )}
          <Button type="submit" disabled={inviteMutation.isPending}>
            {inviteMutation.isPending ? "Inviting…" : "Invite"}
          </Button>
        </form>
      )}

      {inviteLink && (
        <p data-testid="invite-link" className="max-w-sm break-all text-center text-sm">
          Share this link (no email is sent yet): {inviteLink}
        </p>
      )}
    </>
  );
}
