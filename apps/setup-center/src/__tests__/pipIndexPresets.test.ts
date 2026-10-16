import { describe, expect, it } from "vitest";

import {
  DEFAULT_PIP_INDEX_PRESET_ID,
  DEFAULT_PIP_INDEX_URL,
  PIP_INDEX_PRESETS,
} from "../constants";

describe("pip index presets", () => {
  it("defaults to the Aliyun preset and its explicit URL", () => {
    const preset = PIP_INDEX_PRESETS.find(
      (candidate) => candidate.id === DEFAULT_PIP_INDEX_PRESET_ID,
    );

    expect(DEFAULT_PIP_INDEX_PRESET_ID).toBe("aliyun");
    expect(preset).toBeDefined();
    expect(DEFAULT_PIP_INDEX_URL).toBe(preset?.url);
    expect(DEFAULT_PIP_INDEX_URL).toBe("https://mirrors.aliyun.com/pypi/simple/");
  });

  it("keeps an explicit URL for the official PyPI preset", () => {
    const official = PIP_INDEX_PRESETS.find((preset) => preset.id === "official");

    expect(official?.url).toBe("https://pypi.org/simple/");
  });
});
