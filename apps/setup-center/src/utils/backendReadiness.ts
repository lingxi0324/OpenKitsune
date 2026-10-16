/** Prefer capability readiness, while retaining compatibility with older backends. */
export function chatIsReady(readiness: Record<string, unknown>): boolean {
  if (typeof readiness.chat_ready === "boolean") return readiness.chat_ready;
  return readiness.ready !== false;
}
