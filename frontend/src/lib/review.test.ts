import { describe, expect, it } from 'vitest';
import type { DocumentSummary, ReviewItemDto, ToolInvocationDto, VerificationDto } from '../api';
import {
  approvalTarget, bandRows, canTakeVerifier, diffParts, fieldTarget, flagReason, formatValue, parseCorrection, reviewReasons,
  verifierCorrection,
} from './review';

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
    version: 1, page: 2, field_class: 'B', verification: null,
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

  it('opens a proposal at its first cited clause, in the version it cites', () => {
    const invocation = {
      id: 'i1', input: { document_id: 'd1' }, document_version: 3,
      sources: [{ element_id: 'e1', page: 7, section: '4. Fees', quote: 'q' }, { element_id: 'e2', page: 2, section: '', quote: 'q' }],
    } as unknown as ToolInvocationDto;
    const documents = [{ id: 'd1', version: 4, title: 'Tremblay IMA' }] as unknown as DocumentSummary[];
    expect(approvalTarget(invocation, documents)).toEqual({
      key: 'approval:i1', documentId: 'd1', version: 3, page: 7, title: 'Tremblay IMA',
    });
  });
});

describe('X1 diff card helpers', () => {
  const base = {
    run_id: 'r1', quote: 'q', grounded: true, validator_errors: [], page_grade: 'GOOD', document_id: 'd1',
    document_title: 'Tremblay IMA', version: 1, page: 2,
  };
  const verification = (over: Partial<VerificationDto>): VerificationDto => ({
    layer: 'vision', verifier: 'gpt-6-luna', read_value: null, outcome: 'disagree', detail: null,
    crop_url: '/reviews/r1/crops/currency', ...over,
  });
  const bands = [
    { band_text: 'On the first $1,000,000', rate_text: '1.00%', up_to_minor: 100000000, rate_bps: '100' },
    { band_text: 'On the next $1,500,000', rate_text: '0.85%', up_to_minor: 250000000, rate_bps: '85' },
  ];
  const table: ReviewItemDto = {
    ...base, field_path: 'fee_tiers', value: bands, field_class: 'A',
    verification: verification({
      read_value: [{ band_text: 'On the first $1,000,000', rate_text: '1.00%' }, { band_text: 'On the next $1,500,000', rate_text: '0.80%' }],
      detail: 'band 2: rate 85 vs 80 bps', crop_url: '/reviews/r1/crops/fee_tiers',
    }),
  };

  it('marks the part of a value that differs from the other reading', () => {
    expect(diffParts('0.85%', '0.80%')).toEqual([
      { text: '0.8', changed: false }, { text: '5', changed: true }, { text: '%', changed: false }]);
    expect(diffParts('CAD', 'CAD')).toEqual([{ text: 'CAD', changed: false }]);
    expect(diffParts('', 'USD')).toEqual([]);
    expect(diffParts('graduated', 'cliff')).toEqual([{ text: 'graduated', changed: true }]);
  });

  it('says why a field was flagged, in words', () => {
    expect(flagReason(table)).toBe('Vision check: band 2: rate 85 vs 80 bps');
    const currency: ReviewItemDto = { ...base, field_path: 'currency', value: 'CAD', field_class: 'A',
      verification: verification({ read_value: 'USD' }) };
    expect(flagReason(currency)).toBe('Vision check read USD, extraction read CAD');
    expect(flagReason({ ...currency, verification: verification({ outcome: 'unreadable', layer: 'ocr_local' }) }))
      .toBe('Local OCR check could not read it');
    expect(flagReason({ ...currency, verification: verification({ outcome: 'error', detail: 'timed out' }) }))
      .toBe('Vision check failed: timed out');
    expect(flagReason({ ...currency, verification: null })).toBeNull();
  });

  it('pairs the two tables band by band and flags the differing band', () => {
    const rows = bandRows(table);
    expect(rows.map((r) => [r.index, r.changed])).toEqual([[1, false], [2, true]]);
    expect(rows[1].extracted?.rate_text).toBe('0.85%');
    expect(rows[1].read?.rate_text).toBe('0.80%');
    const shorter = { ...table, verification: verification({ read_value: (table.verification!.read_value as unknown[]).slice(0, 1) }) };
    expect(bandRows(shorter).map((r) => [r.index, r.read === null, r.changed])).toEqual([[1, false, false], [2, true, true]]);
  });

  it("offers the verifier's value only when it can replace the extracted one", () => {
    expect(canTakeVerifier(table)).toBe(true);
    const shorter = { ...table, verification: verification({ read_value: (table.verification!.read_value as unknown[]).slice(0, 1) }) };
    expect(canTakeVerifier(shorter)).toBe(false);  // a band count mismatch can only be rejected or retyped
    const currency: ReviewItemDto = { ...base, field_path: 'currency', value: 'CAD', field_class: 'A',
      verification: verification({ read_value: 'USD' }) };
    expect(canTakeVerifier(currency)).toBe(true);
    expect(canTakeVerifier({ ...currency, verification: verification({ read_value: null }) })).toBe(false);
    expect(canTakeVerifier({ ...currency, verification: null })).toBe(false);
  });

  it('turns a verifier band into the correction the API expects', () => {
    expect(verifierCorrection(table)).toEqual(table.verification!.read_value);
  });
});
