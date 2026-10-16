import { describe, expect, it, vi } from "vitest";

import type { ChatConversation } from "../chatTypes";
import {
  isStorageQuotaExceededError,
  persistStorageValueWithMessageEviction,
  retryStorageWriteAfterMessageEviction,
  type ChatStorage,
} from "../storageRecovery";

function conversation(id: string, timestamp: number): ChatConversation {
  return { id, timestamp, title: id, lastMessage: "", messageCount: 0 };
}

function memoryStorage(initial: Record<string, string>): ChatStorage & { values: Map<string, string> } {
  const values = new Map(Object.entries(initial));
  return {
    values,
    get length() { return values.size; },
    key: (index) => [...values.keys()][index] ?? null,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
    removeItem: (key) => { values.delete(key); },
  };
}

describe("isStorageQuotaExceededError", () => {
  it("recognizes browser quota errors without requiring a DOMException instance", () => {
    expect(isStorageQuotaExceededError({ name: "QuotaExceededError" })).toBe(true);
    expect(isStorageQuotaExceededError({ code: 22 })).toBe(true);
    expect(isStorageQuotaExceededError(new Error("storage exceeded the quota"))).toBe(true);
    expect(isStorageQuotaExceededError(new Error("permission denied"))).toBe(false);
  });
});

describe("retryStorageWriteAfterMessageEviction", () => {
  it("evicts orphaned caches before known conversations", () => {
    const storage = memoryStorage({
      "chat_msgs_default_orphan": "old",
      "chat_msgs_default_known": "known",
    });
    const tryWrite = vi.fn(() => !storage.values.has("chat_msgs_default_orphan"));

    const result = retryStorageWriteAfterMessageEviction({
      storage,
      messageKeyPrefix: "chat_msgs_default_",
      conversations: [conversation("known", 10)],
      activeConversationId: null,
      tryWrite,
    });

    expect(result).toEqual({
      succeeded: true,
      evictedKeys: ["chat_msgs_default_orphan"],
    });
    expect(storage.values.has("chat_msgs_default_known")).toBe(true);
  });

  it("evicts non-active conversations from oldest to newest until the write succeeds", () => {
    const storage = memoryStorage({
      "chat_msgs_default_oldest": "one",
      "chat_msgs_default_newer": "two",
      "chat_msgs_default_active": "three",
    });
    const tryWrite = vi.fn(() => (
      !storage.values.has("chat_msgs_default_oldest")
      && !storage.values.has("chat_msgs_default_newer")
    ));

    const result = retryStorageWriteAfterMessageEviction({
      storage,
      messageKeyPrefix: "chat_msgs_default_",
      conversations: [
        conversation("active", 30),
        conversation("newer", 20),
        conversation("oldest", 10),
      ],
      activeConversationId: "active",
      tryWrite,
    });

    expect(result).toEqual({
      succeeded: true,
      evictedKeys: ["chat_msgs_default_oldest", "chat_msgs_default_newer"],
    });
    expect(storage.values.has("chat_msgs_default_active")).toBe(true);
    expect(tryWrite).toHaveBeenCalledTimes(2);
  });

  it("reports failure without evicting the active conversation", () => {
    const storage = memoryStorage({ "chat_msgs_default_active": "keep" });

    const result = retryStorageWriteAfterMessageEviction({
      storage,
      messageKeyPrefix: "chat_msgs_default_",
      conversations: [conversation("active", 10)],
      activeConversationId: "active",
      tryWrite: () => false,
    });

    expect(result).toEqual({ succeeded: false, evictedKeys: [] });
    expect(storage.values.has("chat_msgs_default_active")).toBe(true);
  });
});

describe("persistStorageValueWithMessageEviction", () => {
  it("recovers a quota-limited write by evicting old message caches", () => {
    const storage = memoryStorage({ "chat_msgs_default_old": "large cache" });
    storage.setItem = (key, value) => {
      if (storage.values.has("chat_msgs_default_old")) {
        throw { name: "QuotaExceededError" };
      }
      storage.values.set(key, value);
    };

    const result = persistStorageValueWithMessageEviction({
      storage,
      key: "openkitsune_data_epoch_default",
      value: "epoch-2",
      messageKeyPrefix: "chat_msgs_default_",
      conversations: [conversation("old", 10)],
      activeConversationId: null,
    });

    expect(result).toEqual({
      succeeded: true,
      evictedKeys: ["chat_msgs_default_old"],
      quotaExceeded: true,
    });
    expect(storage.values.get("openkitsune_data_epoch_default")).toBe("epoch-2");
  });

  it("returns a failed result instead of throwing when quota recovery is impossible", () => {
    const quotaError = { name: "QuotaExceededError" };
    const storage = memoryStorage({ "chat_msgs_default_active": "keep" });
    storage.setItem = () => { throw quotaError; };

    const result = persistStorageValueWithMessageEviction({
      storage,
      key: "openkitsune_data_epoch_default",
      value: "epoch-2",
      messageKeyPrefix: "chat_msgs_default_",
      conversations: [conversation("active", 10)],
      activeConversationId: "active",
    });

    expect(result).toEqual({
      succeeded: false,
      evictedKeys: [],
      quotaExceeded: true,
      error: quotaError,
    });
    expect(storage.values.has("chat_msgs_default_active")).toBe(true);
  });
});
