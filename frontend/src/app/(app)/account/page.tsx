"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";

export default function AccountPage() {
  const { user } = useAuth();

  return (
    <>
      <h1 className="text-2xl font-semibold">Account</h1>
      {user && (
        <div data-testid="account-info" className="text-center">
          <p>Email: {user.email}</p>
          <p>User ID: {user.id}</p>
        </div>
      )}

      {user?.active_org_id && (
        <div className="flex gap-3">
          <Link href={`/orgs/${user.active_org_id}/members`} className="text-sm underline">
            View members
          </Link>
          <Link href={`/orgs/${user.active_org_id}/documents`} className="text-sm underline">
            View documents
          </Link>
        </div>
      )}
    </>
  );
}
