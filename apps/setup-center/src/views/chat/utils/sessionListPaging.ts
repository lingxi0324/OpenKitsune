import type { ChatConversation } from "./chatTypes";

export const SESSION_LIST_PAGE_LIMIT = 60;

export type SessionListPageState = {
  query: string;
  nextOffset: number;
  total: number;
  hasMore: boolean;
  loading: boolean;
};

export type ConversationListRow =
  | { kind: "section"; id: "pinned" | "conversations"; label: string }
  | { kind: "conversation"; conversation: ChatConversation };

export function sessionListPageUrl(
  apiBaseUrl: string,
  offset: number,
  query = "",
): string {
  const params = new URLSearchParams({
    channel: "desktop",
    limit: String(SESSION_LIST_PAGE_LIMIT),
    offset: String(Math.max(0, offset)),
  });
  const normalizedQuery = query.trim();
  if (normalizedQuery) params.set("q", normalizedQuery);
  return `${apiBaseUrl}/api/sessions?${params.toString()}`;
}

export function sessionListPageStateFromPayload(
  payload: Record<string, unknown>,
  offset: number,
  received: number,
  query: string,
): SessionListPageState {
  const total = typeof payload.total === "number" && Number.isFinite(payload.total)
    ? Math.max(0, payload.total)
    : offset + received;
  const hasMore = payload.has_more === true;
  const payloadNextOffset = payload.next_offset;
  const nextOffset = hasMore && typeof payloadNextOffset === "number" && Number.isFinite(payloadNextOffset)
    ? Math.max(offset + received, payloadNextOffset)
    : offset + received;
  return {
    query,
    nextOffset,
    total,
    hasMore,
    loading: false,
  };
}

export function buildConversationListRows(
  pinned: ChatConversation[],
  conversations: ChatConversation[],
  labels: { pinned: string; conversations: string },
): ConversationListRow[] {
  const rows: ConversationListRow[] = [];
  if (pinned.length > 0) {
    rows.push({ kind: "section", id: "pinned", label: labels.pinned });
    rows.push(...pinned.map((conversation) => ({ kind: "conversation" as const, conversation })));
  }
  if (conversations.length > 0) {
    rows.push({
      kind: "section",
      id: "conversations",
      label: labels.conversations,
    });
    rows.push(...conversations.map((conversation) => ({
      kind: "conversation" as const,
      conversation,
    })));
  }
  return rows;
}
