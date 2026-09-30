import type { Root, Heading } from "mdast";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import { toString } from "mdast-util-to-string";
import { visit } from "unist-util-visit";

const parser = unified().use(remarkParse).use(remarkGfm);
const debateRoles: Record<string, string> = {
  bull_history: "Bull Analyst",
  bear_history: "Bear Analyst",
  aggressive_history: "Aggressive Analyst",
  conservative_history: "Conservative Analyst",
  neutral_history: "Neutral Analyst",
};

export function reportTurns(section: string, text: string): string[] {
  const role = debateRoles[section];
  if (!role) return [text];
  const markers: { start: number; end: number }[] = [];
  const literals: { start: number; end: number }[] = [];
  visit(parser.parse(text), (node) => {
    if (["code", "inlineCode", "html"].includes(node.type)) {
      literals.push({
        start: node.position?.start.offset ?? 0,
        end: node.position?.end.offset ?? 0,
      });
    }
  });
  // The graph appends only one newline, so a boundary can be a lazy Markdown
  // list/quote/table continuation. Read unindented source lines, excluding literals.
  for (const match of text.matchAll(new RegExp(`^${role}: ?`, "gm"))) {
    if (
      literals.some(
        (range) => match.index >= range.start && match.index < range.end,
      )
    )
      continue;
    markers.push({ start: match.index, end: match.index + match[0].length });
  }
  // Ambiguous or legacy text stays whole rather than losing an introduction.
  if (!markers.length || text.slice(0, markers[0].start).trim()) return [text];
  const turns = markers.map((marker, index) =>
    text.slice(marker.end, markers[index + 1]?.start ?? text.length),
  );
  return turns.every((turn) => turn.trim()) ? turns : [text];
}

export type Chapter = { id: string; label: string; depth: number };
function headingId(prefix: string, node: Heading) {
  return `${prefix}-heading-${node.position?.start.offset ?? 0}`;
}

export function reportChapters(text: string, prefix: string): Chapter[] {
  const chapters: Chapter[] = [];
  visit(parser.parse(text), "heading", (node) => {
    const label = toString(node).trim();
    if (label)
      chapters.push({ id: headingId(prefix, node), label, depth: node.depth });
  });
  return chapters;
}

export function remarkHeadingIds(prefix: string) {
  return (tree: Root) => {
    visit(tree, "heading", (node) => {
      node.data = {
        ...node.data,
        hProperties: {
          ...node.data?.hProperties,
          id: headingId(prefix, node),
          tabIndex: -1,
        },
      };
    });
  };
}
