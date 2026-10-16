import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../chatTypes";
import { chooseHydratedMessages, messageHistoryRichness, patchMessagesWithBackendDetailed } from "../chatHelpers";

const user: ChatMessage = {
  id: "user-1",
  role: "user",
  content: "你好",
  timestamp: 1,
};

describe("chat error hydration", () => {
  it("prefers a finalized error card over a stale streaming placeholder", () => {
    const streaming: ChatMessage = {
      id: "assistant-1",
      role: "assistant",
      content: "",
      timestamp: 2,
      streaming: true,
    };
    const error: ChatMessage = {
      ...streaming,
      streaming: false,
      errorInfo: {
        message: "无法下发组织指令。当前状态：休眠",
        category: "unknown",
      },
    };

    expect(messageHistoryRichness([user, error]))
      .toBeGreaterThan(messageHistoryRichness([user, streaming]));
  });

  it("hydrates a persisted backend error onto the local placeholder", () => {
    const local: ChatMessage[] = [
      user,
      {
        id: "assistant-local",
        role: "assistant",
        content: "",
        timestamp: 2,
        streaming: true,
      },
    ];
    const backend: ChatMessage[] = [
      user,
      {
        id: "assistant-backend",
        role: "assistant",
        content: "",
        timestamp: 3,
        errorInfo: {
          message: "无法下发组织指令。当前状态：休眠",
          category: "unknown",
        },
      },
    ];

    const hydrated = chooseHydratedMessages(local, backend);

    expect(hydrated[1].errorInfo?.message).toBe("无法下发组织指令。当前状态：休眠");
  });
});

describe("completion action hydration", () => {
  it("restores persisted completion actions onto a local assistant message", () => {
    const local: ChatMessage[] = [
      user,
      {
        id: "assistant-local",
        historyIndex: 1,
        role: "assistant",
        content: "diagnosis",
        timestamp: 2,
      },
    ];

    const result = patchMessagesWithBackendDetailed(local, [
      {
        id: "assistant-backend",
        index: 1,
        role: "assistant",
        content: "diagnosis",
        completion_actions: [{ type: "submit_feedback", style: "prominent" }],
      },
    ]);

    expect(result.messages[1].completionActions).toEqual([
      { type: "submit_feedback", style: "prominent" },
    ]);
  });
});

describe("IM mirror hydration", () => {
  it("appends a backend-only assistant message with its delivered image", () => {
    const local: ChatMessage[] = [
      {
        id: "user-local",
        historyIndex: 0,
        role: "user",
        content: "[来自微信] 生成一张海景图",
        timestamp: 1,
      },
    ];
    const backend: ChatMessage[] = [
      local[0],
      {
        id: "assistant-backend",
        historyIndex: 1,
        role: "assistant",
        content: "[回复到微信] 已生成并发送海景图",
        timestamp: 2,
        artifacts: [
          {
            artifact_type: "image",
            file_url: "/api/files?path=generated.png&conversation_id=wechat-mirror",
            path: "C:/workspace/generated.png",
            name: "generated.png",
            caption: "海景图",
          },
        ],
      },
    ];

    const hydrated = chooseHydratedMessages(local, backend);

    expect(hydrated).toHaveLength(2);
    expect(hydrated[1].content).toContain("已生成并发送海景图");
    expect(hydrated[1].artifacts).toEqual(backend[1].artifacts);
  });
});
