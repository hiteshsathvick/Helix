"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { createOrg, switchOrg } from "@/lib/orgs-api";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export default function NewOrgPage() {
  const { accessToken, applySession, user } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  const createMutation = useMutation({
    mutationFn: async () => {
      const org = await createOrg(accessToken!, name, slug || slugify(name));
      // Creating an org may have set it as the caller's active org (if they
      // had none before) — re-issue the token via switch so the frontend
      // session reflects that immediately, same call the org switcher uses.
      const response = await switchOrg(accessToken!, org.id);
      applySession(response);
      return org;
    },
    onSuccess: (org) => router.push(`/orgs/${org.id}/members`),
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken) return;
    createMutation.mutate();
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">Create an organization</h1>
      <form onSubmit={handleSubmit} className="flex w-full max-w-sm flex-col gap-3">
        <Input
          type="text"
          placeholder="Organization name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
        />
        <Input
          type="text"
          placeholder={`Slug (default: ${slugify(name) || "auto-generated"})`}
          value={slug}
          onChange={(event) => setSlug(event.target.value)}
        />
        {createMutation.isError && (
          <Alert data-testid="create-org-error">
            {createMutation.error instanceof Error
              ? createMutation.error.message
              : "failed to create organization"}
          </Alert>
        )}
        <Button type="submit" disabled={createMutation.isPending || !user}>
          {createMutation.isPending ? "Creating…" : "Create organization"}
        </Button>
      </form>
    </>
  );
}
