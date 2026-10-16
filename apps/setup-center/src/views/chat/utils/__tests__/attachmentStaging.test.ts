import { describe, expect, it } from "vitest";

import type { ChatAttachment } from "../chatTypes";
import {
  isAttachmentStillPreparing,
  toChatAttachmentRequest,
} from "../attachmentStaging";

function attachment(overrides: Partial<ChatAttachment> = {}): ChatAttachment {
  return {
    type: "document",
    name: "report.pdf",
    ...overrides,
  };
}

describe("attachment staging contract", () => {
  it("does not treat an unverified local path as a sendable upload", () => {
    expect(isAttachmentStillPreparing(attachment({
      localPath: "D:/files/report.pdf",
      uploadStatus: "uploaded",
    }))).toBe(true);
  });

  it("accepts server upload and working-directory references", () => {
    expect(isAttachmentStillPreparing(attachment({ uploadId: "upload-1" }))).toBe(false);
    expect(isAttachmentStillPreparing(attachment({
      source: "working_directory",
      relativePath: "docs/report.pdf",
    }))).toBe(false);
  });

  it("omits client local paths from chat request payloads", () => {
    const payload = toChatAttachmentRequest(attachment({
      localPath: "D:/files/report.pdf",
      uploadId: "upload-1",
      url: "/api/uploads/upload-1.pdf",
    }));

    expect(payload).toMatchObject({
      source: "upload",
      upload_id: "upload-1",
      url: "/api/uploads/upload-1.pdf",
    });
    expect(payload).not.toHaveProperty("local_path");
  });
});
