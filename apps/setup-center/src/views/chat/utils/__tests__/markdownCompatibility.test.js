// @vitest-environment node
import { build } from "esbuild";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { Worker } from "node:worker_threads";
import { beforeAll, describe, expect, it } from "vitest";

let render;
let preprocessMath;
let autolink;
let bundleSource;

beforeAll(async () => {
  // Use the real dependency graph and production lowering: esbuild converts
  // unsupported regex literals to RegExp constructors, not a regex polyfill.
  const bundle = await build({
    stdin: {
      contents: `
        import React from 'react';
        import { renderToStaticMarkup } from 'react-dom/server';
        import Markdown from 'react-markdown';
        import gfm from './src/views/chat/utils/remarkGfm';
        import {linkifyMarkdown} from './src/views/chat/utils/markdownAutolinks';
        export { preprocessMath } from './src/views/chat/utils/mathPreprocess';
        export { linkifyText } from './src/views/chat/utils/markdownAutolinks';
        export function autolink(text) {
          const tree = {type: 'paragraph', children: [{type: 'text', value: text}]};
          linkifyMarkdown(tree);
          return tree;
        }
        export function render(text) {
          return renderToStaticMarkup(React.createElement(Markdown, {remarkPlugins: [gfm]}, text));
        }
      `,
      resolveDir: process.cwd(),
    },
    bundle: true, platform: "node", format: "cjs", target: ["safari14"], write: false,
  });
  bundleSource = bundle.outputFiles[0].text;
  const NativeRegExp = RegExp;
  const oldRegExp = new Proxy(NativeRegExp, {
    construct(target, args) {
      if (/\(\?<([=!])/.test(String(args[0]))) {
        throw new SyntaxError("Lookbehind is unavailable in this simulated WKWebView");
      }
      return Reflect.construct(target, args);
    },
  });
  const module = { exports: {} };
  const require = createRequire(resolve("package.json"));
  // Inject the legacy constructor into the bundle's scope (including all
  // dependencies), without altering Vitest's own runtime.
  new Function("module", "exports", "require", "RegExp", bundle.outputFiles[0].text)(
    module, module.exports, require, oldRegExp,
  );
  ({ render, preprocessMath, autolink } = module.exports);
});

describe("Markdown on engines without regex lookbehind", () => {
  it("renders plain text, GFM tables, tasks and strikethrough", () => {
    expect(render("Hello world")).toBe("<p>Hello world</p>");
    expect(render("| a | b |\n| - | - |\n| c | d |")).toContain("<table>");
    expect(render("- [x] done")).toContain('type="checkbox"');
    expect(render("~~old~~")).toContain("<del>old</del>");
  });

  it.each([
    ["test@example.com", "test@example.com"],
    ["(test@example.com)", "test@example.com"],
    ["中文test@example.com", "test@example.com"],
    ["/test@example.com", null],
    ["中文+test@example.com", "+test@example.com"],
    ["💰test@example.com", "test@example.com"],
  ])("preserves email boundaries for %s", (text, email) => {
    const html = render(text);
    if (email) expect(html).toContain(`href="mailto:${email}"`);
    else expect(html).not.toContain('href="mailto:');
  });

  it("preserves the autolink transform's boundary checks and surrounding text", () => {
    for (const text of ["/test@example.com", "test@example.com1"]) {
      expect(autolink(text).children).toEqual([{ type: "text", value: text }]);
    }
    const tree = autolink("中文+test@example.com,second@example.org!");
    expect(tree.children.filter((node) => node.type === "link").map((node) => node.url))
      .toEqual(["mailto:+test@example.com", "mailto:second@example.org"]);
    expect(tree.children.filter((node) => node.type === "text").map((node) => node.value).join(""))
      .toBe("中文,!");
  });

  it("preserves URLs and existing links", () => {
    expect(render("https://example.com")).toContain('href="https://example.com"');
    expect(render("[test@example.com](https://example.com)").match(/<a /g)).toHaveLength(1);
  });

  it("normalizes formulas and removes backtick noise without damaging fences", () => {
    expect(preprocessMath('\\(x+1\\)')).toBe('$x+1$');
    expect(preprocessMath('a ``  `` b')).toBe('a  b');
    expect(preprocessMath('`` `` `` ``')).toBe(' ');
    expect(preprocessMath('```js\nconst x = 1;\n```')).toBe('```js\nconst x = 1;\n```');
    expect(preprocessMath('```js\nconst x = 1;')).toBe('```js\nconst x = 1;');
    expect(preprocessMath('`code` and $5')).toBe('`code` and \\$5');
  });

  it("bounds work on long rejected candidates and many adjacent links", async () => {
    // A worker deadline can interrupt a pathological regexp; an in-process
    // test timeout cannot interrupt a synchronous catastrophic backtrack.
    const worker = new Worker(`
      const { parentPort, workerData } = require('node:worker_threads');
      const module = {exports: {}};
      new Function('module', 'exports', 'require', workerData)(module, module.exports, require);
      const inputs = [
        'a'.repeat(800000),
        'a'.repeat(800000) + '@bad',
        'www.'.repeat(100000),
        'https://'.repeat(100000),
        'a@b.com '.repeat(30000),
      ];
      for (const text of inputs) {
        const nodes = module.exports.linkifyText(text);
        const restored = nodes.map(n => n.type === 'text' ? n.value : n.children[0].value).join('');
        if (restored !== text) throw new Error('Text was lost');
      }
      parentPort.postMessage('ok');
    `, { eval: true, workerData: bundleSource });
    try {
      await new Promise((resolve, reject) => {
        const deadline = setTimeout(() => reject(new Error("Autolink scan exceeded 5 seconds")), 5000);
        worker.once("message", () => { clearTimeout(deadline); resolve(); });
        worker.once("error", (error) => { clearTimeout(deadline); reject(error); });
      });
    } finally {
      await worker.terminate();
    }
  }, 10000);
});
