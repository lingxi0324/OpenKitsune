import { describe, expect, it } from "vitest";
import { chatIsReady } from "../utils/backendReadiness";

describe("chat readiness", () => {
  it("allows chat while optional channels are still starting or failed", () => {
    expect(chatIsReady({ chat_ready: true, ready: false, im_ready: false })).toBe(true);
  });
  it("does not mistake HTTP readiness for chat readiness", () => {
    expect(chatIsReady({ http_ready: true, chat_ready: false, ready: true })).toBe(false);
  });
  it("supports older backend readiness responses", () => {
    expect(chatIsReady({ ready: false })).toBe(false);
    expect(chatIsReady({ ready: true })).toBe(true);
    expect(chatIsReady({})).toBe(true);
  });
});
