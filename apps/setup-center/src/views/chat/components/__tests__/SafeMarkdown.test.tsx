import { cleanup, render } from "@testing-library/react";
import ReactMarkdown from "react-markdown";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SafeMarkdown } from "../SafeMarkdown";
import * as math from "../../utils/mathPreprocess";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Markdown failure isolation", () => {
  it("keeps healthy messages formatted and failed messages as escaped text", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const brokenPlugin = () => () => { throw new SyntaxError("Invalid regular expression"); };
    const raw = '**broken**\n<script>alert(1)</script>';
    const { container } = render(<>
      <SafeMarkdown renderer={ReactMarkdown} remarkPlugins={[brokenPlugin]}>{raw}</SafeMarkdown>
      <SafeMarkdown renderer={ReactMarkdown}>**healthy**</SafeMarkdown>
    </>);
    expect(container.firstElementChild?.textContent).toBe(raw);
    expect(container.firstElementChild).toHaveStyle({ whiteSpace: "pre-wrap" });
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("strong")?.textContent).toBe("healthy");
    expect(container.textContent).not.toContain("渲染异常");
  });

  it("continues updating failed streaming content without retrying the renderer", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const renderer = vi.fn(() => { throw new Error("renderer failed"); });
    const { container, rerender } = render(<SafeMarkdown renderer={renderer}>first</SafeMarkdown>);
    const attempts = renderer.mock.calls.length;
    rerender(<SafeMarkdown renderer={renderer}>{'first\nsecond'}</SafeMarkdown>);
    expect(container.textContent).toBe('first\nsecond');
    expect(renderer).toHaveBeenCalledTimes(attempts);
  });

  it("also catches preprocessing failures and preserves the original input", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(math, "preprocessMath").mockImplementation(() => { throw new Error("preprocessing failed"); });
    const { container } = render(<SafeMarkdown renderer={ReactMarkdown}>{'\\(x+1\\)'}</SafeMarkdown>);
    expect(container.textContent).toBe('\\(x+1\\)');
  });
});
