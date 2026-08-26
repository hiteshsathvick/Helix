"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { listMyOrgs, switchOrg } from "@/lib/orgs-api";

export function OrgSwitcher() {
  const { user, accessToken, applySession } = useAuth();
  const queryClient = useQueryClient();

  const { data: orgs = [] } = useQuery({
    queryKey: ["orgs", "mine", accessToken],
    queryFn: () => listMyOrgs(accessToken!),
    enabled: !!accessToken,
  });

  const switchMutation = useMutation({
    mutationFn: (orgId: string) => switchOrg(accessToken!, orgId),
    onSuccess: (response) => {
      applySession(response);
      queryClient.invalidateQueries({ queryKey: ["orgs", "mine"] });
    },
  });

  if (!accessToken) return null;

  return (
    <div className="flex flex-col items-center gap-2" data-testid="org-switcher">
      <div className="flex flex-wrap items-center justify-center gap-2">
        {orgs.length === 0 && <span className="text-sm text-gray-500">No organizations yet</span>}
        {orgs.map((org) => (
          <button
            key={org.id}
            onClick={() => {
              if (org.id !== user?.active_org_id) switchMutation.mutate(org.id);
            }}
            disabled={switchMutation.isPending}
            data-testid={`org-option-${org.slug}`}
            className={`rounded border px-3 py-1 text-sm disabled:opacity-50 ${
              org.id === user?.active_org_id ? "bg-black text-white" : ""
            }`}
          >
            {org.name}
          </button>
        ))}
      </div>
      <Link href="/orgs/new" className="text-sm underline">
        + New organization
      </Link>
    </div>
  );
}
