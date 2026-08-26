import { API_URL, toApiError } from "./api";

export type Citation = {
  document_id: string;
  document_title: string;
  chunk_id: string;
  ordinal: number;
  snippet: string;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  tokens: number;
  cost: number;
  created_at: string;
};

export type ConversationSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = ConversationSummary & {
  messages: Message[];
};

export type AssistantEvent =
  | { type: "token"; text: string }
  | { type: "done"; conversation_id: string; message_id: string; citations: Citation[] };

export async function listConversations(
  accessToken: string,
  orgId: string
): Promise<ConversationSummary[]> {
  const response = await fetch(`${API_URL}/api/v1/orgs/${orgId}/conversations`, {
    credentials: "include",
    cache: "no-store",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function getConversation(
  accessToken: string,
  orgId: string,
  conversationId: string
): Promise<ConversationDetail> {
  const response = await fetch(`${API_URL}/api/v1/orgs/${orgId}/conversations/${conversationId}`, {
    credentials: "include",
    cache: "no-store",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

// EventSource can't send an Authorization header, so this parses the SSE
// stream by hand over a normal authenticated fetch instead.
export async function* streamQuery(
  accessToken: string,
  orgId: string,
  query: string,
  conversationId?: string
): AsyncGenerator<AssistantEvent> {
  const response = await fetch(`${API_URL}/api/v1/orgs/${orgId}/assistant/query`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ query, conversation_id: conversationId }),
  });
  if (!response.ok) throw await toApiError(response);
  if (!response.body) throw new Error("assistant response had no body");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      if (event.startsWith("data: ")) {
        yield JSON.parse(event.slice("data: ".length)) as AssistantEvent;
      }
    }
  }
}
