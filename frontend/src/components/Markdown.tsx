import { type Inline, parseMarkdown } from '../lib/markdown';

interface InlinesProps {
  inlines: Inline[];
}

function Inlines({ inlines }: InlinesProps) {
  return (
    <>
      {inlines.map((inline, index) =>
        inline.kind === 'strong' ? <strong key={index}>{inline.text}</strong> : <span key={index}>{inline.text}</span>,
      )}
    </>
  );
}

interface MarkdownProps {
  text: string;
  className?: string;
}

export function Markdown({ text, className }: MarkdownProps) {
  return (
    <div className={className}>
      {parseMarkdown(text).map((block, index) => {
        if (block.kind === 'heading') {
          return (
            <p key={index} className="markdown__heading">
              <Inlines inlines={block.inlines} />
            </p>
          );
        }
        if (block.kind === 'paragraph') {
          return (
            <p key={index}>
              <Inlines inlines={block.inlines} />
            </p>
          );
        }
        const items = block.items.map((item, itemIndex) => (
          <li key={itemIndex}>
            <Inlines inlines={item} />
          </li>
        ));
        return block.ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
      })}
    </div>
  );
}
