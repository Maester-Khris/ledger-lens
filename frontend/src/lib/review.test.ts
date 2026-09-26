import { describe, expect, it } from 'vitest';
import type { ReviewItemDto } from '../api';
import { formatValue, parseCorrection, reviewReasons } from './review';

describe('formatValue', () => {
  it('shows strings as-is and everything else as JSON', () => {
    expect(formatValue('graduated')).toBe('graduated');
    expect(formatValue(30)).toBe('30');
    expect(formatValue([{ up_to: 1000000, rate_bps: 100 }])).toBe('[{"up_to":1000000,"rate_bps":100}]');
  });
});

describe('parseCorrection', () => {
  it('parses JSON when it can and keeps plain text otherwise', () => {
    expect(parseCorrection('30')).toBe(30);
    expect(parseCorrection('[1,2]')).toEqual([1, 2]);
    expect(parseCorrection('"USD"')).toBe('USD');
    expect(parseCorrection('graduated')).toBe('graduated');
  });

  it('treats blank or null input as no correction', () => {
    expect(parseCorrection('   ')).toBeUndefined();
    expect(parseCorrection('null')).toBeUndefined();
  });
});

describe('reviewReasons', () => {
  const item: ReviewItemDto = {
    run_id: 'r1', field_path: 'fee_method', value: 'cliff', quote: 'on the entire', grounded: false,
    validator_errors: ['tiers overlap'], page_grade: 'FAIR', document_id: 'd1', document_title: 'Tremblay IMA',
    version: 1, page: 2,
  };

  it('explains why a field was held back', () => {
    expect(reviewReasons(item)).toEqual([
      'The quote was not found in the cited text.',
      'Validator: tiers overlap',
      'Page quality is FAIR (needs GOOD or better).',
    ]);
  });

  it('returns nothing for a grounded field on a good page', () => {
    expect(reviewReasons({ ...item, grounded: true, validator_errors: [], page_grade: 'GOOD' })).toEqual([]);
  });
});
