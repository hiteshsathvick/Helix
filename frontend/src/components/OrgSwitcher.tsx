"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { listMyOrgs, switchOrg, type Org } from "@/lib/orgs-api";

export function OrgSwitcher() {
  const { user, accessToken, applySession } = useAuth();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [switching, setSwitching] = useState(false);

  useEffect(() => {
    if (!accessToken) return;
    listMyOrgs(accessToken)
      .then(setOrgs)
      .catch(() => setOrgs([]));
  }, [accessToken, user?.active_org_id]);

  async function handleSwitch(orgId: string) {
    if (!accessToken || orgId === user?.active_org_id) return;
    setSwitching(true);
    try {
      const response = await switchOrg(accessToken, orgId);
      applySession(response);
    } finally {
      setSwitching(false);
    }
  }

  if (!accessToken) return null;

  return (
    <div className="flex flex-col items-center gap-2" data-testid="org-switcher">
      <div className="flex flex-wrap items-center justify-center gap-2">
        {orgs.length === 0 && <span className="text-sm text-gray-500">No organizations yet</span>}
        {orgs.map((org) => (
          <button
            key={org.id}
            onClick={() => handleSwitch(org.id)}
            disabled={switching}
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
