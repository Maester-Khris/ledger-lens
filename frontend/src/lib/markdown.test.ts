import { describe, expect, it } from 'vitest';
import { parseInline, parseMarkdown } from './markdown';

describe('parseMarkdown', () => {
  it('returns no blocks for empty text', () => {
    expect(parseMarkdown('')).toEqual([]);
  });

  it('splits paragraphs on blank lines and joins wrapped lines', () => {
    expect(parseMarkdown('First line\nstill first.\n\nSecond.')).toEqual([
      { kind: 'paragraph', inlines: [{ kind: 'text', text: 'First line still first.' }] },
      { kind: 'paragraph', inlines: [{ kind: 'text', text: 'Second.' }] },
    ]);
  });

  it('renders dash and star bullets as one unordered list', () => {
    expect(parseMarkdown('- one\n* two')).toEqual([
      { kind: 'list', ordered: false, items: [[{ kind: 'text', text: 'one' }], [{ kind: 'text', text: 'two' }]] },
    ]);
  });

  it('renders numbered lines as an ordered list', () => {
    expect(parseMarkdown('1. one\n2) two')).toEqual([
      { kind: 'list', ordered: true, items: [[{ kind: 'text', text: 'one' }], [{ kind: 'text', text: 'two' }]] },
    ]);
  });

  it('starts a list right after a paragraph line', () => {
    expect(parseMarkdown('Fees:\n- 1.00% on the first $1,000,000')).toEqual([
      { kind: 'paragraph', inlines: [{ kind: 'text', text: 'Fees:' }] },
      { kind: 'list', ordered: false, items: [[{ kind: 'text', text: '1.00% on the first $1,000,000' }]] },
    ]);
  });

  it('does not treat a line starting with bold as a bullet', () => {
    expect(parseMarkdown('**Total**: 1,500.00')).toEqual([
      { kind: 'paragraph', inlines: [{ kind: 'strong', text: 'Total' }, { kind: 'text', text: ': 1,500.00' }] },
    ]);
  });

  it('keeps a dash in the middle of a sentence as text', () => {
    expect(parseMarkdown('From $1,000 - $2,000 the rate is 0.85%.')).toEqual([
      { kind: 'paragraph', inlines: [{ kind: 'text', text: 'From $1,000 - $2,000 the rate is 0.85%.' }] },
    ]);
  });

  it('renders a hash line as a heading', () => {
    expect(parseMarkdown('### Fee schedule')).toEqual([
      { kind: 'heading', inlines: [{ kind: 'text', text: 'Fee schedule' }] },
    ]);
  });
});

describe('parseInline', () => {
  it('splits bold spans from text', () => {
    expect(parseInline('Rate is **1.00%** per year')).toEqual([
      { kind: 'text', text: 'Rate is ' },
      { kind: 'strong', text: '1.00%' },
      { kind: 'text', text: ' per year' },
    ]);
  });
});
