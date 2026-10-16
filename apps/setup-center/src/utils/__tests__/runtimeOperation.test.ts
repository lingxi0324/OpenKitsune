import { describe, expect, it } from "vitest";

import {
  connectionStatus,
  decodeRuntimeOperationResponse,
  operationStatus,
  responseFailure,
  runtimeNotice,
} from "../runtimeOperation";

describe("runtime operation response helpers", () => {
  it("separates operation and connection status in the unified contract", () => {
    const response = {
      status: "partial",
      operation_status: "ok",
      connection_status: "connected",
    };

    expect(operationStatus(response)).toBe("ok");
    expect(connectionStatus(response)).toBe("connected");
  });

  it("supports status fields returned by older backends", () => {
    expect(operationStatus({ status: "ok" })).toBe("ok");
    expect(connectionStatus({ status: "already_connected" })).toBe("already_connected");
    expect(connectionStatus({ operation_status: "disconnected" })).toBe("disconnected");
  });

  it("prefers runtime failures and otherwise reports runtime warnings", () => {
    expect(runtimeNotice({
      runtime: {
        failed: { agent_pool: "unavailable" },
        warnings: ["takes effect after reload"],
      },
    })).toBe("agent_pool: unavailable");
    expect(runtimeNotice({ runtime: { warnings: ["takes effect after reload"] } }))
      .toBe("takes effect after reload");
  });

  it("extracts structured and legacy operation failures", () => {
    expect(responseFailure({ ok: false, error: { message: "permission denied" } }))
      .toBe("permission denied");
    expect(responseFailure({ error: "install failed" })).toBe("install failed");
    expect(responseFailure({ ok: true })).toBeNull();
  });

  it("decodes the body, operation failure, and runtime notice once", async () => {
    const decoded = await decodeRuntimeOperationResponse(
      {
        json: async () => ({
          ok: false,
          error: { message: "permission denied" },
          runtime: { warnings: ["restart required"] },
        }),
      },
      "save failed",
    );

    expect(decoded.body.ok).toBe(false);
    expect(decoded.failure).toBe("permission denied");
    expect(decoded.notice).toBe("restart required");
  });

  it("only accepts an empty response when explicitly allowed", async () => {
    const response = { json: async () => { throw new SyntaxError("empty"); } };

    await expect(decodeRuntimeOperationResponse(response, "save failed"))
      .rejects.toThrow("save failed");
    await expect(decodeRuntimeOperationResponse(response, "save failed", { allowEmpty: true }))
      .resolves.toEqual({ body: {}, failure: null, notice: null });
  });
});
