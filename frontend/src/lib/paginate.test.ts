import { describe, expect, it } from 'vitest';
import { paginate } from './paginate';

const ITEMS = [1, 2, 3, 4, 5, 6, 7];

describe('paginate', () => {
  it('slices one page', () => {
    expect(paginate(ITEMS, 1, 5)).toEqual({ items: [1, 2, 3, 4, 5], page: 1, pageCount: 2 });
  });

  it('returns the partial last page', () => {
    expect(paginate(ITEMS, 2, 5)).toEqual({ items: [6, 7], page: 2, pageCount: 2 });
  });

  it('clamps a page that no longer exists after the list shrinks', () => {
    expect(paginate([1, 2], 3, 5)).toEqual({ items: [1, 2], page: 1, pageCount: 1 });
  });

  it('has one empty page for an empty list', () => {
    expect(paginate([], 1, 5)).toEqual({ items: [], page: 1, pageCount: 1 });
  });
});
