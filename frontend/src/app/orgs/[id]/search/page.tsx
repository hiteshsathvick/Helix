"use client";

import { useParams } from "next/navigation";
import { type FormEvent, type ReactNode, useState } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/lib/auth-context";
import { search, type SearchResult } from "@/lib/search-api";

// Matches search.service.HIGHLIGHT_START/STOP on the backend — control
// characters, not HTML tags, precisely so this can highlight matches by
// splitting the string rather than parsing snippet text as HTML (chunk
// content is untrusted; see CLAUDE.md §5).
const HIGHLIGHT_START = "\u0001";
const HIGHLIGHT_STOP = "\u0002";

function renderSnippet(snippet: string): ReactNode[] {
  const segments = snippet.split(HIGHLIGHT_START);
  const nodes: ReactNode[] = [segments[0]];
  for (let i = 1; i < segments.length; i++) {
    const [highlighted, ...rest] = segments[i].split(HIGHLIGHT_STOP);
    nodes.push(
      <mark key={i} className="rounded bg-yellow-200 px-0.5 text-black">
        {highlighted}
      </mark>
    );
    nodes.push(rest.join(HIGHLIGHT_STOP));
  }
  return nodes;
}

function SearchContent() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  async function runSearch(cursor?: string) {
    if (!accessToken || !query.trim()) return;
    setLoading(true);
    setSearchError(null);
    try {
      const response = await search(accessToken, orgId, query, cursor);
      setResults((prev) => (cursor ? [...prev, ...response.results] : response.results));
      setNextCursor(response.next_cursor);
      setHasSearched(true);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "search failed");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    runSearch();
  }

  return (
    <main className="flex min-h-screen flex-col items-center gap-6 p-24">
      <h1 className="text-2xl font-semibold">Search</h1>

      <form onSubmit={handleSubmit} className="flex w-full max-w-md gap-2">
        <input
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search documents…"
          data-testid="search-input"
          className="flex-1 rounded border px-3 py-2"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="rounded border px-4 py-2 disabled:opacity-50"
        >
          Search
        </button>
      </form>

      {searchError && <p className="text-red-600">{searchError}</p>}

      {hasSearched && !loading && results.length === 0 && !searchError && (
        <p className="text-gray-500">No results found.</p>
      )}

      <ul data-testid="search-results" className="flex w-full max-w-md flex-col gap-4">
        {results.map((result) => (
          <li key={result.chunk_id} className="flex flex-col gap-1 border-b pb-3">
            <span className="font-medium">{result.document_title}</span>
            <span className="text-sm text-gray-700">{renderSnippet(result.snippet)}</span>
          </li>
        ))}
      </ul>

      {nextCursor && (
        <button
          onClick={() => runSearch(nextCursor)}
          disabled={loading}
          className="text-sm underline disabled:opacity-50"
        >
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </main>
  );
}

export default function SearchPage() {
  return (
    <ProtectedRoute>
      <SearchContent />
    </ProtectedRoute>
  );
}
