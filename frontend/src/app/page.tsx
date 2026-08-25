"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchHealth } from "@/lib/api";

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; status: string }
  | { kind: "error"; message: string };

export default function HomePage() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    fetchHealth()
      .then((data) => setHealth({ kind: "ok", status: data.status }))
      .catch((err) =>
        setHealth({ kind: "error", message: err instanceof Error ? err.message : "unknown error" })
      );
  }, []);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-24">
      <h1 className="text-2xl font-semibold">Helix</h1>
      {health.kind === "loading" && <p>Checking backend health…</p>}
      {health.kind === "ok" && <p data-testid="health-status">Backend status: {health.status}</p>}
      {health.kind === "error" && (
        <p data-testid="health-error" className="text-red-600">
          Backend unreachable: {health.message}
        </p>
      )}
      <nav className="flex gap-4">
        <Link href="/login" className="underline">
          Log in
        </Link>
        <Link href="/register" className="underline">
          Register
        </Link>
        <Link href="/account" className="underline">
          Account
        </Link>
      </nav>
    </main>
  );
}
