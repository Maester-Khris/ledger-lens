import { describe, expect, it } from 'vitest';
import { clampPage, nextZoom, citationTarget } from './viewer';

describe('clampPage', () => {
  it('keeps a valid page', () => {
    expect(clampPage(3, 10)).toBe(3);
  });

  it('opens page 1 for a missing or non-positive page', () => {
    expect(clampPage(null, 10)).toBe(1);
    expect(clampPage(undefined, 10)).toBe(1);
    expect(clampPage(0, 10)).toBe(1);
  });

  it('opens the last page for a page beyond the end', () => {
    expect(clampPage(42, 10)).toBe(10);
  });
});

describe('nextZoom', () => {
  it('steps through the zoom levels and stops at the ends', () => {
    expect(nextZoom(1, 1)).toBe(1.25);
    expect(nextZoom(1, -1)).toBe(0.75);
    expect(nextZoom(2, 1)).toBe(2);
    expect(nextZoom(0.5, -1)).toBe(0.5);
  });

  it('restarts from 100% for an unknown level', () => {
    expect(nextZoom(1.1, 1)).toBe(1.25);
  });
});

describe('citationTarget', () => {
  const element = { id: 'e1', kind: 'element' as const, document_id: 'd1', document_title: 'Tremblay IMA', version: 2, page: 3 };

  it('points at the cited page of the cited version', () => {
    expect(citationTarget(element)).toEqual({ documentId: 'd1', version: 2, page: 3, title: 'Tremblay IMA' });
  });

  it('has no target for a citation without a page (system and tool citations)', () => {
    expect(citationTarget({ id: 'system', kind: 'system', source: 'indexed contracts' })).toBeNull();
    expect(citationTarget({ ...element, page: undefined })).toBeNull();
    expect(citationTarget({ ...element, document_id: undefined })).toBeNull();
  });

  it('falls back to a generic title', () => {
    expect(citationTarget({ ...element, document_title: undefined })?.title).toBe('Document');
  });
});
