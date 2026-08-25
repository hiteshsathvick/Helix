"use client";

import { useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/lib/auth-context";

function AccountContent() {
  const { user, logout } = useAuth();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-24">
      <h1 className="text-2xl font-semibold">Account</h1>
      {user && (
        <div data-testid="account-info" className="text-center">
          <p>Email: {user.email}</p>
          <p>User ID: {user.id}</p>
        </div>
      )}
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
