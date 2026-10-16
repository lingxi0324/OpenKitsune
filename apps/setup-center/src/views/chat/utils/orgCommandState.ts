export interface ActiveOrgCommand {
  orgId: string;
  commandId: string;
}

export type ActiveOrgCommandsByConversation = ReadonlyMap<string, ActiveOrgCommand>;

export function getActiveOrgCommand(
  commands: ActiveOrgCommandsByConversation,
  conversationId: string | null | undefined,
): ActiveOrgCommand | null {
  if (!conversationId) return null;
  return commands.get(conversationId) ?? null;
}

export function setActiveOrgCommand(
  commands: ActiveOrgCommandsByConversation,
  conversationId: string,
  command: ActiveOrgCommand,
): ActiveOrgCommandsByConversation {
  const next = new Map(commands);
  next.set(conversationId, command);
  return next;
}

export function clearActiveOrgCommand(
  commands: ActiveOrgCommandsByConversation,
  conversationId: string,
  expectedCommandId?: string,
): ActiveOrgCommandsByConversation {
  const current = commands.get(conversationId);
  if (!current || (expectedCommandId && current.commandId !== expectedCommandId)) {
    return commands;
  }
  const next = new Map(commands);
  next.delete(conversationId);
  return next;
}
