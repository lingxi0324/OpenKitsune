import type { Root } from "mdast";
import type { Plugin } from "unified";
import type {} from "remark-parse";
import { gfmFootnote } from "micromark-extension-gfm-footnote";
import { gfmStrikethrough } from "micromark-extension-gfm-strikethrough";
import { gfmTable } from "micromark-extension-gfm-table";
import { gfmTaskListItem } from "micromark-extension-gfm-task-list-item";
import { gfmFootnoteFromMarkdown } from "mdast-util-gfm-footnote";
import { gfmStrikethroughFromMarkdown } from "mdast-util-gfm-strikethrough";
import { gfmTableFromMarkdown } from "mdast-util-gfm-table";
import { gfmTaskListItemFromMarkdown } from "mdast-util-gfm-task-list-item";
import { linkifyMarkdown } from "./markdownAutolinks";

/** Read-only Markdown pipeline: register public syntax/AST extension pairs.
 * Autolinks are owned locally so older WKWebView engines need no regex patches.
 * Serialization extensions are unnecessary: this pipeline only renders Markdown.
 */
const remarkGfm: Plugin<[], Root> = function () {
  const data = this.data();
  (data.micromarkExtensions ||= []).push(
    gfmFootnote(), gfmStrikethrough(), gfmTable(), gfmTaskListItem(),
  );
  (data.fromMarkdownExtensions ||= []).push(
    gfmFootnoteFromMarkdown(), gfmStrikethroughFromMarkdown(),
    gfmTableFromMarkdown(), gfmTaskListItemFromMarkdown(),
  );
  return linkifyMarkdown;
};

export default remarkGfm;
