import { afterEach, describe, expect, it, vi } from "vitest";
import { applySearchHighlights } from "../MessageList";

describe("message search highlights", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("selects individual occurrences within and across messages and clears both highlights", () => {
    const highlights = new Map<string, Set<Range>>();
    vi.stubGlobal("CSS", { highlights });
    vi.stubGlobal("Highlight", class extends Set<Range> {
      constructor(...ranges: Range[]) { super(ranges); }
    });
    const container = document.createElement("div");
    container.innerHTML = '<div class="chatMdContent">Hello hello</div><div class="chatMdContent"><strong>HELLO</strong> world</div>';
    const second = container.children[1] as HTMLElement;
    const texts = (name: string) => [...highlights.get(name)!].map(range => range.toString());

    expect(applySearchHighlights(container, " hello ", 0).count).toBe(3);
    expect(texts("msg-search")).toEqual(["hello", "HELLO"]);
    expect(texts("msg-search-active")).toEqual(["Hello"]);

    const { activeRange } = applySearchHighlights(container, "hello", 1);
    expect(activeRange?.startOffset).toBe(6);
    expect(texts("msg-search-active")).toEqual(["hello"]);

    applySearchHighlights(container, "hello", 2);
    expect(texts("msg-search")).toEqual(["Hello", "hello"]);
    expect(texts("msg-search-active")).toEqual(["HELLO"]);

    second.append(" hello");
    expect(applySearchHighlights(container, "hello", 3).count).toBe(4);
    expect(texts("msg-search-active")).toEqual(["hello"]);

    applySearchHighlights(container, "missing", 3);
    expect(texts("msg-search")).toEqual([]);
    expect(texts("msg-search-active")).toEqual([]);

    applySearchHighlights(container, "hello", 0);
    applySearchHighlights(container, "");
    expect(highlights.size).toBe(0);
  });

  it("matches rendered inline text, excludes controls and does not join paragraphs", () => {
    const container = document.createElement("div");
    container.innerHTML = '<button>hello</button><div class="chatMdContent"><p>he<strong>ll</strong>o</p><p>hel</p><p>lo</p><button>hello</button><span hidden>hello</span><pre><code><span>a</span>+b</code></pre></div>';
    const result = applySearchHighlights(container, "hello");
    expect(result.count).toBe(1);
    expect(result.activeRange?.toString()).toBe("hello");
    expect(applySearchHighlights(container, "a+b").count).toBe(1);
  });
});
