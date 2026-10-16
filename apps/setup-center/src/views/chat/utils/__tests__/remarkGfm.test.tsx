import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import rehypeHighlight from "rehype-highlight";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import remarkGfm from "../remarkGfm";
import { linkifyText } from "../markdownAutolinks";
import { useMdModules } from "../../hooks/useMdModules";

afterEach(cleanup);

function render(text: string) {
  return renderToStaticMarkup(<ReactMarkdown
    remarkPlugins={[remarkGfm, remarkMath]}
    rehypePlugins={[rehypeRaw, rehypeSanitize, rehypeHighlight]}
  >{text}</ReactMarkdown>);
}

describe("composed GFM extensions", () => {
  it("keeps formulas, highlighting and sanitization in the actual shared pipeline", async () => {
    const { result } = renderHook(() => useMdModules());
    await waitFor(() => expect(result.current).not.toBeNull());
    const mods = result.current!;
    const html = renderToStaticMarkup(<mods.ReactMarkdown
      remarkPlugins={mods.remarkPlugins} rehypePlugins={mods.rehypePlugins}
    >{'\\(x+1\\)\n\n```js\nconst x = 1;\n```\n\nhttps://example.com\n\n<script>alert(1)</script>'}</mods.ReactMarkdown>);
    expect(html).toContain('class="katex"');
    expect(html).toContain('hljs');
    expect(html).toContain('href="https://example.com"');
    expect(html).not.toContain('<script>');
  });

  it("preserves tables, task lists, strikethrough and footnotes together", () => {
    const html = render('| a | b |\n| :- | -: |\n| ~~old~~ | new |\n\n- [x] done[^1]\n\n[^1]: note');
    expect(html).toContain("<table>");
    expect(html).toContain("<del>old</del>");
    expect(html).toContain('type="checkbox"');
    expect(html).toContain('checked=""');
    expect(html).toContain("data-footnotes");
    expect(html).toContain("note");
  });

  it.each([
    ['https://example.com/a_(b).', ['https://example.com/a_(b)']],
    ['(https://example.com/a).', ['https://example.com/a']],
    ['www.example.com, HTTP://example.org!', ['http://www.example.com', 'HTTP://example.org']],
    ['mail a+b@example.com, next@example.org.', ['mailto:a+b@example.com', 'mailto:next@example.org']],
    ['中文test@example.com', ['mailto:test@example.com']],
    ['README.md example.com javascript:alert(1)', []],
    ['/test@example.com bad@a_b.com a..b@example.com', []],
    ['https:// https://user:pass@example.com', []],
  ])("finds safe links in %s", (text, expected) => {
    const nodes = linkifyText(text);
    expect(nodes.filter((node) => node.type === "link").map((node) => node.url)).toEqual(expected);
    expect(nodes.map((node) => node.type === "text" ? node.value : node.children[0].type === "text" ? node.children[0].value : "").join(""))
      .toBe(text);
  });

  it("does not nest links or touch code, math, image alt text, or raw HTML anchors", () => {
    const html = render([
      '[https://example.com](https://target.test)',
      '`https://inline.test`',
      '```js\nconst url = "https://code.test";\n```',
      '$www.math.test$',
      '![www.alt.test](https://image.test/a.png)',
      '<a href="https://raw.test">https://inside.test</a>',
      '<code>www.rawcode.test</code>',
    ].join('\n\n'));
    expect(html.match(/<a /g)).toHaveLength(2);
    expect(html).toContain('href="https://target.test"');
    expect(html).toContain('href="https://raw.test"');
    expect(html).toContain('hljs');
    expect(html).not.toContain('mailto:');
  });

  it("retains CommonMark links and sanitizes unsafe HTML and destinations", () => {
    const html = render('[bad](javascript:alert) <https://good.test>\n\n<script>alert(1)</script>');
    expect(html).not.toContain('href="javascript:');
    expect(html).not.toContain('<script>');
    expect(html).toContain('href="https://good.test"');
  });

  it("handles streamed incomplete links without throwing or dropping source", () => {
    const message = 'See https://example.com and user@example.org.';
    for (let i = 0; i <= message.length; i++) {
      const prefix = message.slice(0, i);
      const nodes = linkifyText(prefix);
      expect(nodes.map((node) => node.type === "text" ? node.value : (node.children[0] as { value: string }).value).join(""))
        .toBe(prefix);
      expect(() => render(prefix)).not.toThrow();
    }
  });
});
