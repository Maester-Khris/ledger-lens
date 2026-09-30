import { describe, expect, it } from 'vitest';
import type { DocumentSummary, ReviewItemDto, ToolInvocationDto } from '../api';
import { approvalTarget, fieldTarget, formatValue, parseCorrection, reviewReasons } from './review';

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

describe('viewer targets', () => {
  const item: ReviewItemDto = {
    run_id: 'r1', field_path: 'fee_method', value: 'cliff', quote: 'q', grounded: false, validator_errors: [],
    page_grade: 'FAIR', document_id: 'd1', document_title: 'Tremblay IMA', version: 2, page: 3,
  };

  it('points a field at its document, version and page', () => {
    expect(fieldTarget(item)).toEqual({
      key: 'field:r1:fee_method', documentId: 'd1', version: 2, page: 3, title: 'Tremblay IMA',
    });
  });

  it('points a correction at the current version of the compared contract', () => {
    const invocation = { id: 'i1', input: { document_id: 'd1' } } as unknown as ToolInvocationDto;
    const documents = [{ id: 'd1', version: 4, title: 'Tremblay IMA' }] as unknown as DocumentSummary[];
    expect(approvalTarget(invocation, documents)).toEqual({
      key: 'approval:i1', documentId: 'd1', version: 4, page: null, title: 'Tremblay IMA',
    });
    expect(approvalTarget({ id: 'i2', input: {} } as unknown as ToolInvocationDto, documents)).toBeNull();
  });
});
