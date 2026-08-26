"use client";

import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Alert, Button, Input, Spinner } from "@/components/ui";
import { HighlightedSnippet } from "@/components/HighlightedSnippet";
import { useAuth } from "@/lib/auth-context";
import { type Citation, streamQuery } from "@/lib/assistant-api";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
};

export default function AssistantPage() {
  const { accessToken } = useAuth();
  const params = useParams<{ id: string }>();
  const orgId = params.id;

  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !input.trim() || streaming) return;

    const query = input.trim();
    setInput("");
    setError(null);
    setStreaming(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: query, citations: [] },
      { role: "assistant", content: "", citations: [] },
    ]);

    try {
      for await (const event of streamQuery(accessToken, orgId, query, conversationId)) {
        if (event.type === "token") {
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = {
              ...next[next.length - 1],
              content: next[next.length - 1].content + event.text,
            };
            return next;
          });
        } else {
          setConversationId(event.conversation_id);
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = { ...next[next.length - 1], citations: event.citations };
            return next;
          });
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "the assistant failed to respond");
    } finally {
      setStreaming(false);
    }
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">Assistant</h1>

      <ul data-testid="assistant-messages" className="flex w-full max-w-2xl flex-col gap-4">
        {messages.map((message, index) => (
          <li
            key={index}
            className={message.role === "user" ? "self-end text-right" : "self-start"}
            data-testid={`assistant-message-${message.role}`}
          >
            <p className="whitespace-pre-wrap">{message.content}</p>
            {message.citations.length > 0 && (
              <ul className="mt-2 flex flex-col gap-1 text-sm text-gray-600">
                {message.citations.map((citation) => (
                  <li key={citation.chunk_id}>
                    <span className="font-medium">{citation.document_title}</span> —{" "}
                    <HighlightedSnippet snippet={citation.snippet} />
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      {streaming && <Spinner label="Thinking…" />}
      {error && <Alert>{error}</Alert>}

      <form onSubmit={handleSubmit} className="flex w-full max-w-2xl gap-2">
        <Input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask a question about your documents…"
          data-testid="assistant-input"
          className="flex-1"
          disabled={streaming}
        />
        <Button type="submit" disabled={streaming || !input.trim()}>
          Send
        </Button>
      </form>
    </>
  );
}
