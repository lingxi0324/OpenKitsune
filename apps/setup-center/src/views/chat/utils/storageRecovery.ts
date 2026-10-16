import type { ChatConversation } from "./chatTypes";

export type ChatStorage = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem" | "key" | "length"
>;

export type StorageEvictionResult = {
  succeeded: boolean;
  evictedKeys: string[];
};

export type StorageWriteRecoveryResult = StorageEvictionResult & {
  quotaExceeded: boolean;
  error?: unknown;
};

export function isStorageQuotaExceededError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { name?: unknown; code?: unknown; message?: unknown };
  if (candidate.name === "QuotaExceededError" || candidate.name === "NS_ERROR_DOM_QUOTA_REACHED") {
    return true;
  }
  if (candidate.code === 22 || candidate.code === 1014) return true;
  return typeof candidate.message === "string" && /quota.*exceed|exceed.*quota/i.test(candidate.message);
}

function storageKeys(storage: ChatStorage): string[] {
  const keys: string[] = [];
  try {
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key) keys.push(key);
    }
  } catch {
    return [];
  }
  return keys;
}

/**
 * Free chat message caches after a write has already failed, retrying after
 * every eviction. Orphaned caches are discarded first, followed by known
 * non-active conversations from oldest to newest.
 */
export function retryStorageWriteAfterMessageEviction(options: {
  storage: ChatStorage;
  messageKeyPrefix: string;
  conversations: readonly ChatConversation[];
  activeConversationId: string | null;
  tryWrite: () => boolean;
}): StorageEvictionResult {
  const {
    storage,
    messageKeyPrefix,
    conversations,
    activeConversationId,
    tryWrite,
  } = options;
  const activeKey = activeConversationId
    ? `${messageKeyPrefix}${activeConversationId}`
    : null;
  const knownKeys = new Set(conversations.map((conversation) => (
    `${messageKeyPrefix}${conversation.id}`
  )));
  const orphanedKeys = storageKeys(storage).filter((key) => (
    key.startsWith(messageKeyPrefix) && key !== activeKey && !knownKeys.has(key)
  ));
  const oldestConversationKeys = [...conversations]
    .filter((conversation) => conversation.id !== activeConversationId)
    .sort((left, right) => left.timestamp - right.timestamp)
    .map((conversation) => `${messageKeyPrefix}${conversation.id}`);
  const candidates = [...new Set([...orphanedKeys, ...oldestConversationKeys])];
  const evictedKeys: string[] = [];

  for (const key of candidates) {
    try {
      if (storage.getItem(key) === null) continue;
      storage.removeItem(key);
      evictedKeys.push(key);
    } catch {
      continue;
    }
    if (tryWrite()) return { succeeded: true, evictedKeys };
  }

  return { succeeded: false, evictedKeys };
}

/** Persist a value without allowing storage failures to escape into UI workflows. */
export function persistStorageValueWithMessageEviction(options: {
  storage: ChatStorage;
  key: string;
  value: string;
  messageKeyPrefix: string;
  conversations: readonly ChatConversation[];
  activeConversationId: string | null;
}): StorageWriteRecoveryResult {
  const { storage, key, value } = options;
  let lastError: unknown;
  const tryWrite = () => {
    try {
      storage.setItem(key, value);
      lastError = undefined;
      return true;
    } catch (error) {
      lastError = error;
      return false;
    }
  };

  if (tryWrite()) {
    return { succeeded: true, evictedKeys: [], quotaExceeded: false };
  }
  if (!isStorageQuotaExceededError(lastError)) {
    return { succeeded: false, evictedKeys: [], quotaExceeded: false, error: lastError };
  }

  const recovery = retryStorageWriteAfterMessageEviction({ ...options, tryWrite });
  return {
    ...recovery,
    quotaExceeded: true,
    ...(recovery.succeeded ? {} : { error: lastError }),
  };
}
