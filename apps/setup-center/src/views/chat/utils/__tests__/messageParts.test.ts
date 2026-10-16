import { describe, expect, it } from "vitest";
import type { ChatMessage, ChatTodo } from "../chatTypes";
import { hasRenderableBody, resolveMessageParts } from "../messageParts";

const todo: ChatTodo = {
  id: "plan-1",
  taskSummary: "Ship the feature",
  status: "in_progress",
  steps: [
    { id: "s1", description: "Inspect", status: "completed" },
    { id: "s2", description: "Patch", status: "in_progress" },
  ],
};

describe("message parts projection", () => {
  it("heals explicit todo-only parts with normal text and tool blocks", () => {
    const msg: ChatMessage = {
      id: "m1",
      role: "assistant",
      content: "Done",
      timestamp: 1,
      todo,
      toolCalls: [
        {
          id: "tool-1",
          tool: "read_file",
          args: { path: "src/app.ts" },
          result: "ok",
          status: "done",
        },
      ],
      parts: [{ kind: "plan", id: "plan:plan-1", todo }],
    };

    expect(resolveMessageParts(msg).map((part) => part.kind)).toEqual(["plan", "text", "tools"]);
  });

  it("heals explicit todo-only parts with a hidden reasoning chain marker", () => {
    const msg: ChatMessage = {
      id: "m2",
      role: "assistant",
      content: "",
      timestamp: 1,
      todo,
      thinkingChain: [
        {
          iteration: 1,
          collapsed: false,
          hasThinking: false,
          toolCalls: [],
          entries: [{ kind: "text", content: "About to inspect files" }],
        },
      ],
      parts: [{ kind: "plan", id: "plan:plan-1", todo }],
    };

    expect(resolveMessageParts(msg).map((part) => part.kind)).toEqual(["reasoning", "plan"]);
  });

  it("does not treat plan cards as assistant message body", () => {
    const msg: ChatMessage = {
      id: "m3",
      role: "assistant",
      content: "",
      timestamp: 1,
      todo,
      parts: [{ kind: "plan", id: "plan:plan-1", todo }],
    };
    const parts = resolveMessageParts(msg);

    expect(hasRenderableBody(msg, parts, true, "")).toBe(false);
  });

  it("restores an optional feature install card without duplicate fallback text", () => {
    const msg: ChatMessage = {
      id: "optional-1",
      role: "assistant",
      content: "浏览器自动化组件需要安装。",
      timestamp: 1,
      optionalFeatureInstall: {
        request_id: "request-1",
        conversation_id: "conversation-1",
        feature_id: "browser.automation",
        title: "安装浏览器自动化组件",
        description: "安装浏览器自动化组件",
        components: [],
        estimated_download_mb: 450,
        estimated_disk_mb: 550,
        status: "pending",
        progress: 0,
        message: "等待用户确认",
      },
    };

    const parts = resolveMessageParts(msg);

    expect(parts.map((part) => part.kind)).toEqual(["optional_feature_install"]);
    expect(hasRenderableBody(msg, parts, true, "")).toBe(true);
  });
});
