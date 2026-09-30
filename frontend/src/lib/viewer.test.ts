import { describe, expect, it } from 'vitest';
import { clampPage, nextZoom } from './viewer';

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
