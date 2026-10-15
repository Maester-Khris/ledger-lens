import { describe, expect, it } from 'vitest';
import type { DocumentSummary } from '../api';
import { STARTERS, startersFor } from './starters';

function doc(id: string, key: string, status: DocumentSummary['status'] = 'ready'): DocumentSummary {
  return {
    id, document_key: key, title: key, source_url: null, version: 1, version_id: `v-${id}`, page_count: 2, byte_size: 1,
    file_sha256: 'x', uploaded_at: '2026-10-01T00:00:00Z', element_count: 1, status, status_note: null, description: null,
    events: [],
  };
}

const DOCS = [doc('1', 'tremblay-ima'), doc('2', 'calamos-emerging-market-equity'), doc('3', 'unknown-key'), doc('4', 'aim-global-trends-advisory', 'processing')];

describe('startersFor', () => {
  it('shows the first question of each ready document when none is selected', () => {
    expect(startersFor(DOCS, null)).toEqual([STARTERS['tremblay-ima'][0], STARTERS['calamos-emerging-market-equity'][0]]);
  });

  it("shows the selected document's own questions", () => {
    expect(startersFor(DOCS, '2')).toEqual(STARTERS['calamos-emerging-market-equity']);
  });

  it('shows nothing for a selected document without starters', () => {
    expect(startersFor(DOCS, '3')).toEqual([]);
  });

  it('shows at most four when no document is selected', () => {
    const many = ['a', 'b', 'c', 'd', 'e'].map((id) => doc(id, 'tremblay-ima'));
    expect(startersFor(many, null)).toHaveLength(4);
  });

  it('shows nothing before the documents have loaded', () => {
    expect(startersFor([], '2')).toEqual([]);
  });
});
