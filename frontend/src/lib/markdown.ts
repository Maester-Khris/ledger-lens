export type Inline = { kind: 'text' | 'strong'; text: string };

export type Block =
  | { kind: 'heading'; inlines: Inline[] }
  | { kind: 'paragraph'; inlines: Inline[] }
  | { kind: 'list'; ordered: boolean; items: Inline[][] };

type ListDraft = { ordered: boolean; items: Inline[][] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;
const BOLD = /\*\*(.+?)\*\*/g;

export function parseInline(text: string): Inline[] {
  const parts: Inline[] = [];
  let last = 0;
  for (const match of text.matchAll(BOLD)) {
    if (match.index > last) parts.push({ kind: 'text', text: text.slice(last, match.index) });
    parts.push({ kind: 'strong', text: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ kind: 'text', text: text.slice(last) });
  return parts;
}

// ponytail: the subset the assistant actually emits (paragraphs, lists, bold, headings); no links, tables or code
export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list = null as ListDraft | null;

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: 'paragraph', inlines: parseInline(paragraph.join(' ')) });
    paragraph = [];
  };
  const flushList = () => {
    if (list) blocks.push({ kind: 'list', ordered: list.ordered, items: list.items });
    list = null;
  };

  for (const line of source.split('\n')) {
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    const heading = HEADING.exec(line);
    const item = bullet ?? numbered;
    if (item) {
      flushParagraph();
      const ordered = bullet === null;
      if (list && list.ordered !== ordered) flushList();
      list ??= { ordered, items: [] };
      list.items.push(parseInline(item[1].trim()));
    } else if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ kind: 'heading', inlines: parseInline(heading[1].trim()) });
    } else if (!line.trim()) {
      flushParagraph();
      flushList();
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}
