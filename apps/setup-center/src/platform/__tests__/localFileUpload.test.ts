import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  class Channel<T> {
    onmessage: (payload: T) => void = () => {};
  }
  return {
    Channel,
    invoke: vi.fn(),
  };
});

vi.mock("../detect", () => ({
  IS_TAURI: true,
  IS_WEB: false,
  IS_CAPACITOR: false,
  IS_LOCAL_WEB: false,
  IS_MOBILE_BROWSER: false,
}));
vi.mock("../auth", () => ({ getAccessToken: () => "desktop-remote-token" }));
vi.mock("@tauri-apps/api/core", () => ({
  Channel: mocks.Channel,
  invoke: mocks.invoke,
}));

import { uploadLocalFile } from "../index";

describe("uploadLocalFile", () => {
  beforeEach(() => mocks.invoke.mockReset());

  it("returns the regular backend upload contract", async () => {
    mocks.invoke.mockResolvedValue({
      status: 200,
      body: JSON.stringify({
        url: "/api/uploads/staged.pdf",
        upload_id: "staged.pdf",
        local_path: "C:/openkitsune/uploads/staged.pdf",
        size: 42,
        mime_type: "application/pdf",
      }),
    });

    const uploaded = await uploadLocalFile(
      "D:/docs/report.pdf",
      "http://127.0.0.1:18900/api/upload",
      "report.pdf",
      "application/pdf",
    );

    expect(uploaded).toEqual({
      url: "/api/uploads/staged.pdf",
      uploadId: "staged.pdf",
      localPath: "C:/openkitsune/uploads/staged.pdf",
      size: 42,
      mimeType: "application/pdf",
    });
    expect(mocks.invoke).toHaveBeenCalledWith("upload_local_file", expect.objectContaining({
      path: "D:/docs/report.pdf",
      authorization: "desktop-remote-token",
    }));
  });

  it("surfaces structured backend upload failures", async () => {
    mocks.invoke.mockResolvedValue({
      status: 413,
      body: JSON.stringify({ detail: "referenced file exceeds 50 MB" }),
    });

    await expect(uploadLocalFile(
      "D:/docs/large.pdf",
      "http://127.0.0.1:18900/api/upload",
      "large.pdf",
    )).rejects.toThrow("referenced file exceeds 50 MB");
  });
});
