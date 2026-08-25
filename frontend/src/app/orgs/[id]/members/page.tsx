"use client";

import { useParams } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/lib/auth-context";
import { inviteMember, listMembers, type Member } from "@/lib/orgs-api";

function MembersContent() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [members, setMembers] = useState<Member[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const loadMembers = useCallback(() => {
    if (!accessToken) return;
    listMembers(accessToken, orgId)
      .then(setMembers)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "failed to load members"));
  }, [accessToken, orgId]);

  useEffect(() => {
    loadMembers();
  }, [loadMembers]);

  async function handleInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken) return;
    setInviteError(null);
    setInviteLink(null);
    setSubmitting(true);
    try {
      const { token } = await inviteMember(accessToken, orgId, email);
      setInviteLink(`${window.location.origin}/invitations/${token}/accept`);
      setEmail("");
      loadMembers();
    } catch (err) {
      setInviteError(err instanceof Error ? err.message : "failed to invite member");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-24">
      <h1 className="text-2xl font-semibold">Members</h1>

      {loadError && <p className="text-red-600">{loadError}</p>}
      <ul data-testid="member-list" className="flex flex-col gap-1">
        {members.map((member) => (
          <li key={member.id}>
            {member.email} — {member.status}
          </li>
        ))}
      </ul>

      <form onSubmit={handleInvite} className="flex w-full max-w-sm flex-col gap-3">
        <input
          type="email"
          placeholder="Invite by email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          className="rounded border px-3 py-2"
        />
        {inviteError && (
          <p data-testid="invite-error" className="text-red-600">
            {inviteError}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-black px-3 py-2 text-white disabled:opacity-50"
        >
          {submitting ? "Inviting…" : "Invite"}
        </button>
      </form>

      {inviteLink && (
        <p data-testid="invite-link" className="max-w-sm break-all text-center text-sm">
          Share this link (no email is sent yet): {inviteLink}
        </p>
      )}
    </main>
  );
}

export default function MembersPage() {
  return (
    <ProtectedRoute>
      <MembersContent />
    </ProtectedRoute>
  );
}
