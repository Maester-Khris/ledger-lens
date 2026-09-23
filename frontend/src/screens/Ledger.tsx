import { useState } from 'react';
import { Link } from 'react-router';
import { CheckIcon, LockIcon, SearchIcon } from '../components/Icons';
import { CopyButton } from '../components/CopyButton';
import { StatusPill, type StatusVariant } from '../components/StatusPill';
import './Ledger.css';

type Source = 'ai' | 'api' | 'stress';
type PostingStatus = 'posted' | 'reversed' | 'reversal';

type JournalLine = {
  account: string;
  debit?: string;
  credit?: string;
};

type Provenance = {
  tool: string;
  toolInvocation: string;
  sourceDoc: string;
  citation: string;
  session: string;
};

type Posting = {
  id: string;
  description: string;
  sub: string;
  amount: string;
  createdAt: string;
  createdAtFull: string;
  source: Source;
  status: PostingStatus;
  idempotencyKey: string;
  lines: JournalLine[];
  provenance?: Provenance;
  reversedBy?: string;
};

const POSTINGS: Posting[] = [
  {
    id: 'pst_98f102a4',
    description: 'Total reported employment income — T4 2024',
    sub: 'tool: total_reported_income · 2024_T4_AcmeCorp.pdf p.1',
    amount: '94,500.00',
    createdAt: 'Sep 22, 14:22 UTC',
    createdAtFull: 'Sep 22, 2026 14:22:04 UTC',
    source: 'ai',
    status: 'posted',
    idempotencyKey: 'doc_7f3a21c9:ti_0192e4b1',
    lines: [
      { account: 'Employment Income Receivable', debit: '94,500.00' },
      { account: 'Reported Income', credit: '94,500.00' },
    ],
    provenance: {
      tool: 'total_reported_income',
      toolInvocation: 'ti_0192e4b1',
      sourceDoc: '2024_T4_AcmeCorp.pdf',
      citation: 'Page 1 · Employment income',
      session: 'ses_5d21',
    },
  },
  {
    id: 'pst_77e034bc',
    description: 'Opening balance — operating cash',
    sub: 'idempotency: seed-opening-001',
    amount: '10,000.00',
    createdAt: 'Sep 22, 13:05 UTC',
    createdAtFull: 'Sep 22, 2026 13:05:41 UTC',
    source: 'api',
    status: 'posted',
    idempotencyKey: 'seed-opening-001',
    lines: [
      { account: 'Operating Cash', debit: '10,000.00' },
      { account: 'Owner Equity', credit: '10,000.00' },
    ],
  },
  {
    id: 'pst_44a109fe',
    description: 'Reversal of pst_62d891ce — duplicate invoice',
    sub: 'Compensates pst_62d891ce',
    amount: '1,250.00',
    createdAt: 'Sep 22, 12:52 UTC',
    createdAtFull: 'Sep 22, 2026 12:52:17 UTC',
    source: 'api',
    status: 'reversal',
    idempotencyKey: 'reverse:pst_62d891ce',
    lines: [
      { account: 'Accounts Payable', debit: '1,250.00' },
      { account: 'Office Expenses', credit: '1,250.00' },
    ],
  },
  {
    id: 'pst_62d891ce',
    description: 'Vendor invoice INV-2291',
    sub: 'Reversed by pst_44a109fe',
    amount: '1,250.00',
    createdAt: 'Sep 22, 12:40 UTC',
    createdAtFull: 'Sep 22, 2026 12:40:09 UTC',
    source: 'api',
    status: 'reversed',
    idempotencyKey: 'inv-2291',
    lines: [
      { account: 'Office Expenses', debit: '1,250.00' },
      { account: 'Accounts Payable', credit: '1,250.00' },
    ],
    reversedBy: 'pst_44a109fe',
  },
  {
    id: 'pst_31b74281',
    description: 'Total reported employment income — W-2 2024',
    sub: 'tool: total_reported_income · 2024_W2_AcmeCorp.pdf p.1',
    amount: '61,300.00',
    createdAt: 'Sep 22, 11:18 UTC',
    createdAtFull: 'Sep 22, 2026 11:18:52 UTC',
    source: 'ai',
    status: 'posted',
    idempotencyKey: 'doc_3b8e0f12:ti_0187c2d6',
    lines: [
      { account: 'Employment Income Receivable', debit: '61,300.00' },
      { account: 'Reported Income', credit: '61,300.00' },
    ],
    provenance: {
      tool: 'total_reported_income',
      toolInvocation: 'ti_0187c2d6',
      sourceDoc: '2024_W2_AcmeCorp.pdf',
      citation: 'Page 1 · Wages, tips, other compensation',
      session: 'ses_5d21',
    },
  },
  {
    id: 'pst_1c0e9d77',
    description: 'Payroll accrual — September',
    sub: 'idempotency: payroll-2026-09',
    amount: '8,420.50',
    createdAt: 'Sep 22, 10:02 UTC',
    createdAtFull: 'Sep 22, 2026 10:02:30 UTC',
    source: 'api',
    status: 'posted',
    idempotencyKey: 'payroll-2026-09',
    lines: [
      { account: 'Payroll Expense', debit: '8,420.50' },
      { account: 'Payroll Payable', credit: '8,420.50' },
    ],
  },
  {
    id: 'pst_0a9f3e21',
    description: 'Hot-account transfer #0187',
    sub: 'idempotency: stress-0187',
    amount: '12.00',
    createdAt: 'Sep 22, 09:41 UTC',
    createdAtFull: 'Sep 22, 2026 09:41:03 UTC',
    source: 'stress',
    status: 'posted',
    idempotencyKey: 'stress-0187',
    lines: [
      { account: 'Stress Hot Account', debit: '12.00' },
      { account: 'Stress Counterparty', credit: '12.00' },
    ],
  },
  {
    id: 'pst_0a9f3e20',
    description: 'Hot-account transfer #0186',
    sub: 'idempotency: stress-0186',
    amount: '7.50',
    createdAt: 'Sep 22, 09:41 UTC',
    createdAtFull: 'Sep 22, 2026 09:41:03 UTC',
    source: 'stress',
    status: 'posted',
    idempotencyKey: 'stress-0186',
    lines: [
      { account: 'Stress Counterparty', debit: '7.50' },
      { account: 'Stress Hot Account', credit: '7.50' },
    ],
  },
];

const SOURCE_FILTERS: { id: 'all' | Source; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'ai', label: 'AI tool' },
  { id: 'api', label: 'API' },
  { id: 'stress', label: 'Stress test' },
];

const SOURCE_CHIP: Record<Source, { variant: StatusVariant; label: string }> = {
  ai: { variant: 'accent', label: 'AI tool' },
  api: { variant: 'neutral', label: 'API' },
  stress: { variant: 'warning', label: 'Stress test' },
};

const STATUS_PILL: Record<PostingStatus, { variant: StatusVariant; label: string }> = {
  posted: { variant: 'success', label: 'Posted' },
  reversed: { variant: 'neutral', label: 'Reversed' },
  reversal: { variant: 'purple', label: 'Reversal' },
};

function total(lines: JournalLine[], side: 'debit' | 'credit'): string {
  const sum = lines.reduce((acc, l) => acc + Number((l[side] ?? '0').replace(/,/g, '')), 0);
  return sum.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function Ledger() {
  const [selectedId, setSelectedId] = useState(POSTINGS[0].id);
  const [query, setQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<'all' | Source>('all');
  const [hideStress, setHideStress] = useState(true);

  const q = query.trim().toLowerCase();
  const rows = POSTINGS.filter(
    (p) =>
      (sourceFilter === 'all' || p.source === sourceFilter) &&
      !(hideStress && p.source === 'stress' && sourceFilter !== 'stress') &&
      (!q || [p.id, p.idempotencyKey, p.description].some((f) => f.toLowerCase().includes(q))),
  );
  const hiddenStress = POSTINGS.filter((p) => p.source === 'stress').length;
  const selected = POSTINGS.find((p) => p.id === selectedId) ?? POSTINGS[0];
  const status = STATUS_PILL[selected.status];

  return (
    <div className="ledger">
      <div className="ledger__topbar">
        <span className="ledger__breadcrumb">
          Ledger / <span>Postings</span>
        </span>
      </div>

      <div className="ledger__body">
        <div className="ledger__header">
          <h1 className="ledger__title">
            Postings
            <span className="ledger__readonly-badge mono">
              <LockIcon size={11} /> Append-only
            </span>
          </h1>
          <p className="ledger__subtitle">
            Every journal entry in the double-entry ledger. Postings are immutable — corrections
            are made by compensating reversals.
          </p>
        </div>

        <div className="ledger__toolbar">
          <div className="ledger__filter-input">
            <SearchIcon size={14} />
            <input
              type="text"
              placeholder="Filter by posting ID, idempotency key, or description…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="segmented" role="group" aria-label="Filter by source">
            {SOURCE_FILTERS.map((f) => (
              <button
                type="button"
                key={f.id}
                className={`segmented__item${sourceFilter === f.id ? ' segmented__item--active' : ''}`}
                onClick={() => setSourceFilter(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <label className="ledger__checkbox">
            <input
              type="checkbox"
              checked={hideStress}
              onChange={(event) => setHideStress(event.target.checked)}
            />
            Hide stress-test postings
          </label>
          <span className="ledger__count mono">{rows.length} postings</span>
        </div>

        <div className="ledger__grid">
          <div className="panel ledger__table-panel">
            <div className="scroll-x">
              <table className="data-table">
                <colgroup>
                  <col className="col-id" />
                  <col />
                  <col className="col-amount" />
                  <col className="col-created" />
                  <col className="col-source" />
                </colgroup>
                <thead>
                  <tr>
                    <th>Posting</th>
                    <th>Description</th>
                    <th style={{ textAlign: 'right' }}>Amount</th>
                    <th>Created</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((posting) => {
                    const pill = STATUS_PILL[posting.status];
                    const chip = SOURCE_CHIP[posting.source];
                    return (
                      <tr
                        key={posting.id}
                        className={posting.id === selectedId ? 'ledger__row--selected' : undefined}
                        onClick={() => setSelectedId(posting.id)}
                      >
                        <td className="mono ledger__id">{posting.id}</td>
                        <td>
                          <div className="ledger__desc">{posting.description}</div>
                          <div className="ledger__desc-sub mono" title={posting.sub}>
                            {posting.sub}
                          </div>
                        </td>
                        <td className="ledger__amount-cell">
                          <div
                            className={`mono ledger__amount${
                              posting.status === 'reversed' ? ' ledger__amount--struck' : ''
                            }`}
                          >
                            {posting.amount} CAD
                          </div>
                          <StatusPill variant={pill.variant}>{pill.label}</StatusPill>
                        </td>
                        <td className="mono ledger__created">{posting.createdAt}</td>
                        <td>
                          <StatusPill variant={chip.variant}>{chip.label}</StatusPill>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="ledger__table-foot">
              <span>
                Showing {rows.length} postings
                {hideStress && sourceFilter !== 'stress' && ` (${hiddenStress} stress-test hidden)`}
              </span>
              <span className="ledger__invariant">
                <CheckIcon size={13} /> Every posting balances — debits = credits enforced by a
                database constraint
              </span>
            </div>
          </div>

          <aside className="panel ledger__detail-panel">
            <div className="ledger__detail-head">
              <span className="ledger__label mono">Posting</span>
              <span className="ledger__detail-id-value mono">{selected.id}</span>
              <CopyButton value={selected.id} />
              <span className="ledger__detail-immutable">
                <StatusPill variant="neutral">
                  <LockIcon size={10} /> Immutable
                </StatusPill>
              </span>
            </div>

            <h2 className="ledger__detail-desc">{selected.description}</h2>
            <div
              className={`ledger__detail-amount mono${
                selected.status === 'reversed' ? ' ledger__amount--struck' : ''
              }`}
            >
              {selected.amount} CAD
            </div>
            <div className="ledger__detail-meta">
              <StatusPill variant={status.variant}>{status.label}</StatusPill>
              <span className="mono">Created {selected.createdAtFull}</span>
            </div>

            <section className="ledger__detail-section">
              <div className="ledger__detail-section-head">
                <span>Journal entries</span>
                <StatusPill variant="success">Balanced</StatusPill>
              </div>
              <table className="ledger__journal">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th className="num">Debit</th>
                    <th className="num">Credit</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.lines.map((line) => (
                    <tr key={line.account}>
                      <td>{line.account}</td>
                      <td className="num mono">{line.debit ?? '—'}</td>
                      <td className="num mono">{line.credit ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td>Total</td>
                    <td className="num mono">{total(selected.lines, 'debit')}</td>
                    <td className="num mono">{total(selected.lines, 'credit')}</td>
                  </tr>
                </tfoot>
              </table>
            </section>

            <section className="ledger__detail-section">
              <div className="ledger__detail-section-head">
                <span>Idempotency</span>
              </div>
              <div className="ledger__key-box mono">
                <span>{selected.idempotencyKey}</span>
                <CopyButton value={selected.idempotencyKey} />
              </div>
              <p className="ledger__help">
                Replaying this key returns this same posting. Same key with a different payload is
                rejected (409).
              </p>
            </section>

            <section className="ledger__detail-section">
              <div className="ledger__detail-section-head">
                <span>AI provenance</span>
              </div>
              {selected.provenance ? (
                <>
                  <dl className="ledger__provenance">
                    <dt>Tool</dt>
                    <dd className="mono">{selected.provenance.tool}</dd>
                    <dt>Tool invocation</dt>
                    <dd className="mono">{selected.provenance.toolInvocation}</dd>
                    <dt>Input</dt>
                    <dd>document_id only (no model-supplied amount)</dd>
                    <dt>Source document</dt>
                    <dd className="mono">{selected.provenance.sourceDoc}</dd>
                    <dt>Citation</dt>
                    <dd>{selected.provenance.citation}</dd>
                    <dt>Chat session</dt>
                    <dd className="mono">{selected.provenance.session}</dd>
                  </dl>
                  <div className="ledger__detail-links">
                    <Link to="/chat">View tool invocation →</Link>
                    <Link to="/documents">View source document →</Link>
                  </div>
                </>
              ) : (
                <p className="ledger__help">Created via POST /postings — no AI provenance.</p>
              )}
            </section>

            <div className="ledger__detail-actions">
              {selected.reversedBy ? (
                <button
                  type="button"
                  className="ledger__link-btn"
                  onClick={() => setSelectedId(selected.reversedBy!)}
                >
                  Reversed by {selected.reversedBy} →
                </button>
              ) : selected.status === 'reversal' ? null : (
                <>
                  <button type="button" className="btn btn-secondary ledger__reverse-btn">
                    Reverse posting
                  </button>
                  <p className="ledger__help">
                    Creates a compensating posting. The original stays in the ledger.
                  </p>
                </>
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
