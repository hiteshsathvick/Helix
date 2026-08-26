import { API_URL, toApiError } from "./api";

export type SearchResult = {
  document_id: string;
  document_title: string;
  chunk_id: string;
  ordinal: number;
  snippet: string;
  score: number;
};

export type SearchResponse = {
  results: SearchResult[];
  next_cursor: string | null;
};

export async function search(
  accessToken: string,
  orgId: string,
  query: string,
  cursor?: string
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (cursor) params.set("cursor", cursor);

  const response = await fetch(`${API_URL}/api/v1/orgs/${orgId}/search?${params}`, {
    credentials: "include",
    cache: "no-store",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}
