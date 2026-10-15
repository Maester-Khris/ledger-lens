import type { PostingDto, PostingSourceDto } from '../api';
import { formatMinor } from './money';

export type PostingStatus = 'posted' | 'reversed' | 'reversal';

export interface JournalLineView {
  account: string;
  debit: string | null;
  credit: string | null;
}

export interface PostingView {
  id: string;
  description: string;
  source: PostingSourceDto;
  status: PostingStatus;
  createdAt: string;
  amount: string;
  idempotencyKey: string;
  reversedBy: string | null;
  reverses: string | null;
  lines: JournalLineView[];
  debitTotal: string;
  creditTotal: string;
  balanced: boolean;
}

function statusOf(posting: PostingDto): PostingStatus {
  if (posting.reversed_by_posting_id) return 'reversed';
  if (posting.reverses_posting_id) return 'reversal';
  return 'posted';
}

// ponytail: totals use the first entry's currency; a multi-currency posting would need one total per currency
export function toPostingView(posting: PostingDto): PostingView {
  const currency = posting.entries[0]?.currency ?? '';
  const total = (side: 'debit' | 'credit') =>
    posting.entries.filter((e) => e.direction === side).reduce((sum, e) => sum + e.amount, 0);
  const debit = total('debit');
  const credit = total('credit');
  return {
    id: posting.id,
    description: posting.description ?? 'No description',
    source: posting.source,
    status: statusOf(posting),
    createdAt: posting.created_at,
    amount: formatMinor(debit, currency),
    idempotencyKey: posting.idempotency_key,
    reversedBy: posting.reversed_by_posting_id,
    reverses: posting.reverses_posting_id,
    lines: posting.entries.map((e) => ({
      account: e.account_name,
      debit: e.direction === 'debit' ? formatMinor(e.amount, e.currency) : null,
      credit: e.direction === 'credit' ? formatMinor(e.amount, e.currency) : null,
    })),
    debitTotal: formatMinor(debit, currency),
    creditTotal: formatMinor(credit, currency),
    balanced: debit === credit,
  };
}
