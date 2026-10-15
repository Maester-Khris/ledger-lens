import { describe, expect, it } from 'vitest';
import type { EntryDto, PostingDto } from '../api';
import { toPostingView } from './postings';

function entry(direction: 'debit' | 'credit', amount: number, name: string): EntryDto {
  return { id: name, account_id: name, account_name: name, currency: 'CAD', direction, amount };
}

function posting(overrides: Partial<PostingDto> = {}): PostingDto {
  return {
    id: 'p1',
    idempotency_key: 'ai:i1',
    description: 'Approved compare_contract_to_billing result',
    effective_at: '2026-09-24T10:00:00Z',
    created_at: '2026-09-24T10:00:00Z',
    source: 'ai_tool',
    reverses_posting_id: null,
    reversed_by_posting_id: null,
    entries: [entry('debit', 150000, 'Fees receivable'), entry('credit', 150000, 'Advisory fee revenue')],
    ...overrides,
  };
}

describe('toPostingView', () => {
  it('uses the debit total as the amount and labels lines by account name', () => {
    const view = toPostingView(posting());
    expect(view.amount).toBe('1,500.00 CAD');
    expect(view.lines).toEqual([
      { account: 'Fees receivable', debit: '1,500.00 CAD', credit: null },
      { account: 'Advisory fee revenue', debit: null, credit: '1,500.00 CAD' },
    ]);
    expect(view.balanced).toBe(true);
  });

  it('flag an unbalanced posting', () => {
    expect(toPostingView(posting({ entries: [entry('debit', 100, 'A'), entry('credit', 90, 'B')] })).balanced).toBe(false);
  });

  it('derives the status from the reversal links', () => {
    expect(toPostingView(posting()).status).toBe('posted');
    expect(toPostingView(posting({ reversed_by_posting_id: 'p2' })).status).toBe('reversed');
    expect(toPostingView(posting({ reverses_posting_id: 'p0' })).status).toBe('reversal');
  });

  it('names a posting without a description', () => {
    expect(toPostingView(posting({ description: null })).description).toBe('No description');
  });
});
