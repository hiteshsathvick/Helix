export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_URL}/health`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`health check failed: ${response.status}`);
  }
  return response.json();
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
    cache: "no-store",
  });
}

export async function toApiError(response: Response): Promise<Error> {
  try {
    const body = await response.json();
    return new Error(body?.error?.message ?? `request failed: ${response.status}`);
  } catch {
    return new Error(`request failed: ${response.status}`);
  }
}
