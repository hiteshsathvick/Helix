import type { ReactNode } from "react";

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

export function HighlightedSnippet({ snippet }: { snippet: string }) {
  return <>{renderSnippet(snippet)}</>;
}
