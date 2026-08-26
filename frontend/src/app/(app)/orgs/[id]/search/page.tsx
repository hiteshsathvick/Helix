"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { type FormEvent, type ReactNode, useState } from "react";
import { Alert, Button, EmptyState, Input, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { search } from "@/lib/search-api";

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

export default function SearchPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [query, setQuery] = useState("");
  // Separate from `query` so typing doesn't trigger a search — only
  // submitting the form (or loading more of the same search) does.
  const [submittedQuery, setSubmittedQuery] = useState("");

  const searchQuery = useInfiniteQuery({
    queryKey: ["search", orgId, submittedQuery],
    queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
      search(accessToken!, orgId, submittedQuery, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: !!accessToken && !!submittedQuery,
  });

  const results = searchQuery.data?.pages.flatMap((page) => page.results) ?? [];

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setSubmittedQuery(query.trim());
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">Search</h1>

      <form onSubmit={handleSubmit} className="flex w-full max-w-md gap-2">
        <Input
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search documents…"
          data-testid="search-input"
          className="flex-1"
        />
        <Button type="submit" variant="secondary" disabled={searchQuery.isFetching || !query.trim()}>
          Search
        </Button>
      </form>

      {searchQuery.isFetching && !searchQuery.isFetchingNextPage && (
        <Spinner label="Searching…" />
      )}
      {searchQuery.isError && (
        <Alert>{searchQuery.error instanceof Error ? searchQuery.error.message : "search failed"}</Alert>
      )}
      {searchQuery.isSuccess && results.length === 0 && <EmptyState>No results found.</EmptyState>}

      <ul data-testid="search-results" className="flex w-full max-w-md flex-col gap-4">
        {results.map((result) => (
          <li key={result.chunk_id} className="flex flex-col gap-1 border-b pb-3">
            <span className="font-medium">{result.document_title}</span>
            <span className="text-sm text-gray-700">{renderSnippet(result.snippet)}</span>
          </li>
        ))}
      </ul>

      {searchQuery.hasNextPage && (
        <Button variant="link" onClick={() => searchQuery.fetchNextPage()} disabled={searchQuery.isFetchingNextPage}>
          {searchQuery.isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      )}
    </>
  );
}
