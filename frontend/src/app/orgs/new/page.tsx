"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/lib/auth-context";
import { createOrg, switchOrg } from "@/lib/orgs-api";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function CreateOrgForm() {
  const { accessToken, applySession, user } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken) return;
    setError(null);
    setSubmitting(true);
    try {
      const org = await createOrg(accessToken, name, slug || slugify(name));
      // Creating an org may have set it as the caller's active org (if they
      // had none before) — re-issue the token via switch so the frontend
      // session reflects that immediately, same call the org switcher uses.
      const response = await switchOrg(accessToken, org.id);
      applySession(response);
      router.push(`/orgs/${org.id}/members`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to create organization");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-24">
      <h1 className="text-2xl font-semibold">Create an organization</h1>
      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-3">
        <input
          type="text"
          placeholder="Organization name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          className="rounded border px-3 py-2"
        />
        <input
          type="text"
          placeholder={`Slug (default: ${slugify(name) || "auto-generated"})`}
          value={slug}
          onChange={(event) => setSlug(event.target.value)}
          className="rounded border px-3 py-2"
        />
        {error && (
          <p data-testid="create-org-error" className="text-red-600">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting || !user}
          className="rounded bg-black px-3 py-2 text-white disabled:opacity-50"
        >
          {submitting ? "Creating…" : "Create organization"}
        </button>
      </form>
    </main>
  );
}

export default function NewOrgPage() {
  return (
    <ProtectedRoute>
      <CreateOrgForm />
    </ProtectedRoute>
  );
}
