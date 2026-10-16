import { describe, expect, it } from "vitest";

import {
  clearActiveOrgCommand,
  getActiveOrgCommand,
  setActiveOrgCommand,
  type ActiveOrgCommandsByConversation,
} from "../orgCommandState";

describe("organization command state", () => {
  it("isolates pending commands by conversation", () => {
    let commands: ActiveOrgCommandsByConversation = new Map();
    commands = setActiveOrgCommand(commands, "conversation-a", {
      orgId: "org-a",
      commandId: "command-a",
    });

    expect(getActiveOrgCommand(commands, "conversation-a")).toEqual({
      orgId: "org-a",
      commandId: "command-a",
    });
    expect(getActiveOrgCommand(commands, "conversation-b")).toBeNull();

    commands = setActiveOrgCommand(commands, "conversation-b", {
      orgId: "org-b",
      commandId: "command-b",
    });
    commands = clearActiveOrgCommand(commands, "conversation-a", "command-a");

    expect(getActiveOrgCommand(commands, "conversation-a")).toBeNull();
    expect(getActiveOrgCommand(commands, "conversation-b")).toEqual({
      orgId: "org-b",
      commandId: "command-b",
    });
  });

  it("does not let a stale terminal event clear a newer command", () => {
    let commands: ActiveOrgCommandsByConversation = setActiveOrgCommand(
      new Map(),
      "conversation-a",
      { orgId: "org-a", commandId: "command-new" },
    );

    const unchanged = clearActiveOrgCommand(commands, "conversation-a", "command-old");

    expect(unchanged).toBe(commands);
    expect(getActiveOrgCommand(unchanged, "conversation-a")?.commandId).toBe("command-new");

    commands = clearActiveOrgCommand(commands, "conversation-a", "command-new");
    expect(getActiveOrgCommand(commands, "conversation-a")).toBeNull();
  });
});
