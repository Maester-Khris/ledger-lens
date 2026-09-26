import { describe, expect, it } from 'vitest';
import { scaleToFit } from './pdf';

describe('PDF scaling', () => {
  it('shrinks the page to fit exactly within both bounds', () => {
    expect(scaleToFit({ w: 1000, h: 2000 }, { w: 100, h: 100 })).toBe(0.05); // h constrained
    expect(scaleToFit({ w: 2000, h: 1000 }, { w: 100, h: 100 })).toBe(0.05); // w constrained
    expect(scaleToFit({ w: 800, h: 1200 }, { w: 400, h: 800 })).toBe(0.5);   // w constrained
    expect(scaleToFit({ w: 800, h: 1200 }, { w: 800, h: 400 })).toBe(1 / 3); // h constrained
  });

  it('grows a small page to fill the available space', () => {
    expect(scaleToFit({ w: 100, h: 200 }, { w: 500, h: 500 })).toBe(2.5); // h constrained
  });
});
