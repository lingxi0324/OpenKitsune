import type { ChatAttachment } from "./chatTypes";

export type ChatAttachmentRequest = {
  type: ChatAttachment["type"];
  source: "upload" | "working_directory";
  relativePath?: string;
  name: string;
  url?: string;
  upload_id?: string;
  size?: number;
  mime_type?: string;
};

export function isAttachmentStillPreparing(att: ChatAttachment): boolean {
  if (att.source === "working_directory") return !att.relativePath;
  if (att.uploadStatus === "uploading") return true;
  return !att.url && !att.uploadId;
}

/** Serialize only server-verifiable attachment references into chat requests. */
export function toChatAttachmentRequest(att: ChatAttachment): ChatAttachmentRequest {
  return {
    type: att.type,
    source: att.source || "upload",
    relativePath: att.relativePath,
    name: att.name,
    url: att.url,
    upload_id: att.uploadId,
    size: att.size,
    mime_type: att.mimeType,
  };
}
