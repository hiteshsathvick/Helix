"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui";
import { OrgSwitcher } from "@/components/OrgSwitcher";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const activeOrgId = user?.active_org_id;

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b px-6 py-4">
        <nav className="flex items-center gap-4 text-sm">
          <Link href="/account" className="font-semibold">
            Helix
          </Link>
          {activeOrgId && (
            <>
              <Link href={`/orgs/${activeOrgId}/documents`} className="underline">
                Documents
              </Link>
              <Link href={`/orgs/${activeOrgId}/connectors`} className="underline">
                Connectors
              </Link>
              <Link href={`/orgs/${activeOrgId}/search`} className="underline">
                Search
              </Link>
              <Link href={`/orgs/${activeOrgId}/assistant`} className="underline">
                Assistant
              </Link>
              <Link href={`/orgs/${activeOrgId}/agents`} className="underline">
                Agents
              </Link>
              <Link href={`/orgs/${activeOrgId}/workflows`} className="underline">
                Workflows
              </Link>
              <Link href={`/orgs/${activeOrgId}/notifications`} className="underline">
                Notifications
              </Link>
              <Link href={`/orgs/${activeOrgId}/members`} className="underline">
                Members
              </Link>
            </>
          )}
        </nav>
        <div className="flex items-center gap-4">
          <OrgSwitcher />
          <Button variant="secondary" onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </header>
      <main className="flex flex-1 flex-col items-center gap-6 p-12">{children}</main>
    </div>
  );
}
