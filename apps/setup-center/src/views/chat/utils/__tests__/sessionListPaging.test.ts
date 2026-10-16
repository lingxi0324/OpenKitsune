import { describe, expect, it } from "vitest";

import type { ChatConversation } from "../chatTypes";
import {
  buildConversationListRows,
  SESSION_LIST_PAGE_LIMIT,
  sessionListPageStateFromPayload,
  sessionListPageUrl,
} from "../sessionListPaging";

function conversation(id: string): ChatConversation {
  return {
    id,
    title: id,
    lastMessage: "",
    timestamp: 0,
    messageCount: 0,
  };
}

describe("sessionListPageUrl", () => {
  it("requests bounded desktop pages and includes trimmed search text", () => {
    const url = new URL(sessionListPageUrl("http://127.0.0.1:18900", 60, "  archived  "));

    expect(url.pathname).toBe("/api/sessions");
    expect(url.searchParams.get("channel")).toBe("desktop");
    expect(url.searchParams.get("limit")).toBe(String(SESSION_LIST_PAGE_LIMIT));
    expect(url.searchParams.get("offset")).toBe("60");
    expect(url.searchParams.get("q")).toBe("archived");
  });
});

describe("sessionListPageStateFromPayload", () => {
  it("keeps the server cursor and total for the next lazy page", () => {
    expect(sessionListPageStateFromPayload(
      { total: 145, has_more: true, next_offset: 120 },
      60,
      60,
      "",
    )).toEqual({
      query: "",
      nextOffset: 120,
      total: 145,
      hasMore: true,
      loading: false,
    });
  });
});

describe("buildConversationListRows", () => {
  it("creates virtual rows with section labels and stable conversation order", () => {
    const rows = buildConversationListRows(
      [conversation("pinned")],
      [conversation("recent"), conversation("older")],
      { pinned: "Pinned", conversations: "Conversations" },
    );

    expect(rows.map((row) => row.kind === "section" ? row.id : row.conversation.id)).toEqual([
      "pinned",
      "pinned",
      "conversations",
      "recent",
      "older",
    ]);
  });
});
