import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EnvMap } from "../../types";
import { useConfigApplyPreview } from "../useConfigApplyPreview";

const safeFetchMock = vi.hoisted(() => vi.fn());

vi.mock("../../providers", () => ({
  safeFetch: (...args: unknown[]) => safeFetchMock(...args),
}));

describe("useConfigApplyPreview", () => {
  beforeEach(() => {
    safeFetchMock.mockReset();
    safeFetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body || "{}")) as { keys?: string[] };
      const applyModes = Object.fromEntries(
        (body.keys || []).map((key) => [
          key,
          key === "API_PORT" ? "process_restart" : "next_task",
        ]),
      );
      return {
        json: async () => ({
          apply_modes: applyModes,
          effective_values: Object.fromEntries(
            (body.keys || []).map((key) => [
              key,
              key === "API_PORT"
                ? "18900"
                : key === "DESKTOP_NOTIFY_ENABLED"
                  ? "false"
                  : "100",
            ]),
          ),
        }),
      };
    });
  });

  it("classifies each field once and reuses its cached mode across edits", async () => {
    type Props = { keys: string[]; draft: EnvMap };
    const baseline = { MAX_ITERATIONS: "100", API_PORT: "18900" };
    const { result, rerender } = renderHook(
      ({ keys, draft }: Props) =>
        useConfigApplyPreview({
          keys,
          draft,
          baseline,
          enabled: true,
          apiBase: "http://localhost:18900",
        }),
      {
        initialProps: {
          keys: ["MAX_ITERATIONS"],
          draft: { MAX_ITERATIONS: "100", API_PORT: "18900" },
        },
      },
    );

    await waitFor(() => expect(safeFetchMock).toHaveBeenCalledTimes(1));

    rerender({
      keys: ["MAX_ITERATIONS"],
      draft: { MAX_ITERATIONS: "200", API_PORT: "18900" },
    });
    await waitFor(() => expect(result.current.counts.next_task).toBe(1));
    expect(safeFetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(safeFetchMock.mock.calls[0][1].body)).toEqual({
      keys: ["MAX_ITERATIONS"],
    });

    rerender({
      keys: ["MAX_ITERATIONS"],
      draft: { MAX_ITERATIONS: "300", API_PORT: "18900" },
    });
    expect(result.current.counts.next_task).toBe(1);
    expect(safeFetchMock).toHaveBeenCalledTimes(1);

    rerender({
      keys: ["MAX_ITERATIONS", "API_PORT"],
      draft: { MAX_ITERATIONS: "300", API_PORT: "19001" },
    });
    await waitFor(() => expect(result.current.counts.process_restart).toBe(1));
    expect(safeFetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(safeFetchMock.mock.calls[1][1].body)).toEqual({ keys: ["API_PORT"] });
  });

  it("treats an omitted false setting as clean after toggling on and off", async () => {
    const { result, rerender } = renderHook(
      ({ draft }: { draft: EnvMap }) =>
        useConfigApplyPreview({
          keys: ["DESKTOP_NOTIFY_ENABLED"],
          draft,
          baseline: {},
          enabled: true,
          apiBase: "http://localhost:18900",
        }),
      { initialProps: { draft: {} } },
    );

    await waitFor(() => expect(safeFetchMock).toHaveBeenCalledTimes(1));
    rerender({ draft: { DESKTOP_NOTIFY_ENABLED: "true" } });
    expect(result.current.dirtyKeys).toEqual(["DESKTOP_NOTIFY_ENABLED"]);

    rerender({ draft: { DESKTOP_NOTIFY_ENABLED: "false" } });
    expect(result.current.dirtyKeys).toEqual([]);
  });
});
