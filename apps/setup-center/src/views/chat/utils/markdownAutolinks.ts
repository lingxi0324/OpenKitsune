import type { Link, Parent, Root, Text } from "mdast";

// Deliberately narrower than the full GFM literal-autolink grammar: HTTP(S),
// www. hosts and ASCII email addresses. No fuzzy domains or arbitrary schemes.
// This runs on decoded text nodes, not source: code, math, explicit links and
// raw HTML must retain their existing meaning.
const LOCAL_CHAR = /[a-z0-9._+-]/i;
const DOMAIN_CHAR = /[a-z0-9.-]/i;
const URL_STOP = /[\s\u0000-\u001f\u007f-\u009f<>"'`\u3000-\u303f\uff00-\uff65]/;
const TRAILING_PUNCTUATION = /[.,!?;:*_~]/;
const PROTECTED_NODES = new Set(["link", "linkReference", "code", "inlineCode", "math", "inlineMath"]);
const PROTECTED_HTML = /^(a|code|pre|script|style|textarea)$/i;

function trimUrl(text: string, start: number, end: number): number {
  const balance = { ")": 0, "]": 0, "}": 0 };
  for (let i = start; i < end; i++) {
    const ch = text[i];
    if (ch === "(") balance[")"]++;
    else if (ch === "[") balance["]"]++;
    else if (ch === "{") balance["}"]++;
    else if (ch === ")" || ch === "]" || ch === "}") balance[ch]--;
  }
  while (end > start) {
    const ch = text[end - 1];
    if (TRAILING_PUNCTUATION.test(ch)) end--;
    else if ((ch === ")" || ch === "]" || ch === "}") && balance[ch] < 0) {
      balance[ch]++;
      end--;
    } else break;
  }
  return end;
}

function validEmail(local: string, domain: string): boolean {
  if (local.length > 64 || local.length + domain.length + 1 > 254 ||
      local.startsWith(".") || local.endsWith(".") || local.includes("..")) return false;
  const labels = domain.split(".");
  return labels.length >= 2 && labels.every((label) =>
    label.length > 0 && label.length <= 63 && !label.startsWith("-") && !label.endsWith("-"),
  ) && /[a-z]$/i.test(domain);
}

/** Scan disjoint candidates, including rejected ones. Never retry their suffixes:
 * a long word without @ or a malformed URL must cost O(n), not O(n squared).
 */
export function linkifyText(text: string): Array<Text | Link> {
  const result: Array<Text | Link> = [];
  let cursor = 0;
  let plainStart = 0;
  function addLink(start: number, end: number, url: string) {
    if (start > plainStart) result.push({ type: "text", value: text.slice(plainStart, start) });
    result.push({ type: "link", url, title: null, children: [{ type: "text", value: text.slice(start, end) }] });
    plainStart = end;
  }
  while (cursor < text.length) {
    const start = cursor;
    const previous = start ? text[start - 1] : "";
    const prefix = text.slice(start, start + 8).toLowerCase();
    const isWww = prefix.startsWith("www.");
    if ((!previous || !/[a-z0-9_@/]/i.test(previous)) &&
        (isWww || prefix.startsWith("https://") || prefix.startsWith("http://"))) {
      while (cursor < text.length && !URL_STOP.test(text[cursor])) cursor++;
      const end = trimUrl(text, start, cursor);
      const candidate = text.slice(start, end);
      const href = isWww ? `http://${candidate}` : candidate;
      try {
        const url = new URL(href);
        // Require a real www host suffix; explicit HTTP(S) also permits localhost
        // and IP literals. Preserve the authored spelling in both href and label.
        if (url.hostname && !url.username && !url.password &&
            (!isWww || /^www\.[a-z0-9-]+(?:\.[a-z0-9-]+)+$/i.test(url.hostname))) {
          addLink(start, end, href);
        }
      } catch { /* Invalid candidates stay ordinary text. */ }
      continue;
    }
    if (LOCAL_CHAR.test(text[cursor])) {
      while (cursor < text.length && LOCAL_CHAR.test(text[cursor])) cursor++;
      const localEnd = cursor;
      if (text[cursor] === "@") {
        cursor++;
        const domainStart = cursor;
        while (cursor < text.length && DOMAIN_CHAR.test(text[cursor])) cursor++;
        let end = cursor;
        while (end > domainStart && text[end - 1] === ".") end--;
        const local = text.slice(start, localEnd);
        const domain = text.slice(domainStart, end);
        if (previous !== "/" && previous !== "@" && text[cursor] !== "_" &&
            validEmail(local, domain)) {
          addLink(start, end, `mailto:${local}@${domain}`);
        }
      }
      continue;
    }
    cursor++;
  }
  if (plainStart < text.length) result.push({ type: "text", value: text.slice(plainStart) });
  return result;
}

/** Only replace eligible text nodes; never generate HTML or nest anchors. */
export function linkifyMarkdown(tree: Root): void {
  const pending: Parent[] = [tree];
  while (pending.length) {
    const parent = pending.pop()!;
    const children: Parent["children"] = [];
    const htmlStack: string[] = [];
    for (const child of parent.children) {
      if (child.type === "html") {
        const tag = /^<\s*(\/?)\s*([a-z][a-z0-9]*)\b/i.exec(child.value);
        if (tag && PROTECTED_HTML.test(tag[2])) {
          const name = tag[2].toLowerCase();
          if (!tag[1] && !/\/\s*>$/.test(child.value)) htmlStack.push(name);
          else if (htmlStack[htmlStack.length - 1] === name) htmlStack.pop();
        }
      }
      if (child.type === "text" && !htmlStack.length) {
        const linked = linkifyText(child.value);
        // Preserve original source positions when there was no replacement.
        if (linked.some((node) => node.type === "link")) {
          for (const node of linked) children.push(node);
        }
        else children.push(child);
      } else {
        children.push(child);
        if (!htmlStack.length && !PROTECTED_NODES.has(child.type) && "children" in child) {
          pending.push(child as Parent);
        }
      }
    }
    parent.children = children;
  }
}
