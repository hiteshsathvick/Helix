"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { OrgSwitcher } from "@/components/OrgSwitcher";
import { useAuth } from "@/lib/auth-context";

function AccountContent() {
  const { user, logout } = useAuth();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-24">
      <h1 className="text-2xl font-semibold">Account</h1>
      {user && (
        <div data-testid="account-info" className="text-center">
          <p>Email: {user.email}</p>
          <p>User ID: {user.id}</p>
        </div>
      )}

      <div className="flex flex-col items-center gap-2">
        <h2 className="text-lg font-medium">Organizations</h2>
        <OrgSwitcher />
        {user?.active_org_id && (
          <Link href={`/orgs/${user.active_org_id}/members`} className="text-sm underline">
            View members
          </Link>
        )}
      </div>

      <button onClick={handleLogout} className="rounded bg-black px-3 py-2 text-white">
        Log out
      </button>
    </main>
  );
}

export default function AccountPage() {
  return (
    <ProtectedRoute>
      <AccountContent />
    </ProtectedRoute>
  );
}
