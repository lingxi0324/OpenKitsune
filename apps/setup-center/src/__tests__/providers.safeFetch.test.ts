import { beforeEach, describe, expect, it, vi } from "vitest";

const authFetch = vi.hoisted(() => vi.fn());

vi.mock("../platform", () => ({
  IS_TAURI: false,
  proxyFetch: vi.fn(),
}));
vi.mock("../platform/auth", () => ({
  authFetch,
  isTauriRemoteMode: () => false,
}));

import { safeFetch, safeFetchResponse } from "../providers";

describe("safeFetchResponse", () => {
  beforeEach(() => authFetch.mockReset());

  it("preserves validation responses for callers that classify HTTP errors", async () => {
    authFetch.mockResolvedValue(new Response(JSON.stringify({
      error: "unverified attachment local_path",
      message: "unverified attachment local_path",
    }), {
      status: 403,
      headers: { "content-type": "application/json" },
    }));

    const response = await safeFetchResponse("http://127.0.0.1:18900/api/chat");

    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({
      error: "unverified attachment local_path",
    });
  });

  it("keeps the existing throwing safeFetch contract", async () => {
    authFetch.mockResolvedValue(new Response(JSON.stringify({ detail: "forbidden" }), {
      status: 403,
    }));

    await expect(safeFetch("http://127.0.0.1:18900/api/chat")).rejects.toThrow("forbidden");
  });
});
