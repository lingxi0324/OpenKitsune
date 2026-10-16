import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";
import i18n from "../../../../i18n";
import type { ChatMessage, ChatTodo } from "../../utils/chatTypes";
import { resolveMessageParts } from "../../utils/messageParts";
import { MessageParts } from "../MessageParts";

beforeEach(async () => {
  await i18n.changeLanguage("zh");
});

const todo: ChatTodo = {
  id: "plan-1",
  taskSummary: "测试任务计划",
  status: "in_progress",
  steps: [
    { id: "s1", description: "第一步：分析", status: "completed" },
    { id: "s2", description: "第二步：实现", status: "in_progress" },
    { id: "s3", description: "第三步：验证", status: "pending" },
  ],
};

it("renders the todo plan card as the first part of an assistant turn", () => {
  const msg: ChatMessage = {
    id: "m1",
    role: "assistant",
    content: "正在执行…",
    timestamp: 1,
    todo,
  };
  const parts = resolveMessageParts(msg);

  // 计划卡片必须排在轮次内容最上方（对话轮次上方），先于正文。
  expect(parts[0].kind).toBe("plan");
  expect(parts.map((p) => p.kind)).toEqual(["plan", "text"]);

  render(
    <MessageParts
      msg={msg}
      parts={parts}
      bodyContent={msg.content}
      formatSourceTags={(t) => t}
    />
  );

  // 计划标题、进度计数（已完成/总数）与各步骤描述都应在页面上。
  expect(screen.getByText("测试任务计划")).toBeInTheDocument();
  expect(screen.getByText("1/3")).toBeInTheDocument();
  expect(screen.getByText(/第一步：分析/)).toBeInTheDocument();
  expect(screen.getByText(/第二步：实现/)).toBeInTheDocument();
  expect(screen.getByText(/第三步：验证/)).toBeInTheDocument();
});
