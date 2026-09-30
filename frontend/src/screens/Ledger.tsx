import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { type PostingPage, type PostingSourceDto, type ToolInvocationDto, listPostings, listToolInvocations, reversePosting } from '../api';
import { CheckIcon, LockIcon, SearchIcon } from '../components/Icons';
import { CopyButton } from '../components/CopyButton';
import { StatusPill, type StatusVariant } from '../components/StatusPill';
import { type PostingStatus, type PostingView, toPostingView } from '../lib/postings';
import { selectableRow } from '../lib/rowSelect';
import { formatUtc, formatUtcFull } from '../lib/time';
import './Ledger.css';

const PAGE_SIZE = 50;

const SOURCE_FILTERS: Array<{ id: 'all' | PostingSourceDto; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'ai_tool', label: 'AI tool' },
  { id: 'fee_run', label: 'Fee run' },
  { id: 'api', label: 'API' },
];

const SOURCE_CHIP: Record<PostingSourceDto, { variant: StatusVariant; label: string }> = {
  ai_tool: { variant: 'accent', label: 'AI tool' },
  fee_run: { variant: 'neutral', label: 'Fee run' },
  api: { variant: 'neutral', label: 'API' },
  stress_test: { variant: 'warning', label: 'Stress test' },
};

const STATUS_PILL: Record<PostingStatus, { variant: StatusVariant; label: string }> = {
  posted: { variant: 'success', label: 'Posted' },
  reversed: { variant: 'neutral', label: 'Reversed' },
  reversal: { variant: 'purple', label: 'Reversal' },
};

interface ProvenanceProps {
  postingId: string;
}

function Provenance({ postingId }: ProvenanceProps) {
  const [invocations, setInvocations] = useState<ToolInvocationDto[] | null>(null);

  useEffect(() => {
    listToolInvocations({ postingId })
      .then(setInvocations)
      .catch(() => setInvocations([]));
  }, [postingId]);

  if (invocations === null) return <p className="ledger__help">Loading provenance…</p>;
  const invocation = invocations[0];
  if (!invocation) return <p className="ledger__help">No tool invocation is linked to this posting.</p>;
  return (
    <dl className="ledger__provenance">
      <dt>Tool</dt>
      <dd className="mono">{invocation.tool_name}</dd>
      <dt>Model</dt>
      <dd className="mono">{invocation.model_id}</dd>
      <dt>Prompt</dt>
      <dd className="mono">{invocation.prompt_version}</dd>
      <dt>Chat session</dt>
      <dd className="mono">{invocation.session_id}</dd>
      <dt>Approved by</dt>
      <dd className="mono">
        {invocation.decision ? `${invocation.decision.decided_by} · ${formatUtc(invocation.decision.decided_at)}` : '—'}
      </dd>
    </dl>
  );
}

interface ReverseActionProps {
  posting: PostingView;
  onReversed: (reversalId: string) => void;
}

function ReverseAction({ posting, onReversed }: ReverseActionProps) {
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reverse = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const reversal = await reversePosting(posting.id);
      onReversed(reversal.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The reversal was not posted');
    } finally {
      setSubmitting(false);
    }
  };

  if (!confirming) {
    return (
      <>
        <button type="button" className="btn btn-secondary ledger__reverse-btn" onClick={() => setConfirming(true)}>
          Reverse posting
        </button>
        <p className="ledger__help">Creates a compensating posting. The original stays in the ledger.</p>
      </>
    );
  }
  return (
    <>
      <div className="ledger__confirm-row">
        <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void reverse()}>
          {submitting ? 'Posting reversal…' : 'Confirm reversal'}
        </button>
        <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => setConfirming(false)}>
          Cancel
        </button>
      </div>
      {error && (
        <p className="ledger__error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

export function Ledger() {
  const [searchParams] = useSearchParams();
  const [postings, setPostings] = useState<PostingView[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get('posting'));
  const [query, setQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<'all' | PostingSourceDto>('all');
  const [includeStress, setIncludeStress] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPage = useCallback(
    (cursor?: string) =>
      listPostings({ source: sourceFilter === 'all' ? undefined : sourceFilter, includeStress, limit: PAGE_SIZE, cursor }),
    [sourceFilter, includeStress],
  );

  const showPage = (page: PostingPage, append: boolean) => {
    const views = page.items.map(toPostingView);
    setPostings((current) => (append ? [...current, ...views] : views));
    setNextCursor(page.next_cursor);
    setError(null);
  };

  const showError = (e: unknown) => setError(e instanceof Error ? e.message : 'Could not load postings');

  // callers flag `loading` from the event that caused the fetch; the effect only sets state once data arrives
  const load = (cursor?: string) =>
    fetchPage(cursor)
      .then((page) => showPage(page, cursor !== undefined))
      .catch(showError)
      .finally(() => setLoading(false));

  useEffect(() => {
    let cancelled = false; // a filter change mid-flight must not let the older response win
    fetchPage()
      .then((page) => !cancelled && showPage(page, false))
      .catch((e: unknown) => !cancelled && showError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [fetchPage]);

  const q = query.trim().toLowerCase();
  const rows = postings.filter(
    (p) => !q || [p.id, p.idempotencyKey, p.description].some((field) => field.toLowerCase().includes(q)),
  );
  const selected = postings.find((p) => p.id === selectedId) ?? rows[0];

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
            Every journal entry in the double-entry ledger. Postings are never edited — a correction is a compensating
            reversal.
          </p>
        </div>

        <div className="ledger__toolbar">
          <div className="ledger__filter-input">
            <SearchIcon size={14} />
            <input
              type="text"
              aria-label="Filter postings"
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
                aria-pressed={sourceFilter === f.id}
                className={`segmented__item${sourceFilter === f.id ? ' segmented__item--active' : ''}`}
                onClick={() => {
                  setLoading(true);
                  setSourceFilter(f.id);
                }}
              >
                {f.label}
              </button>
            ))}
          </div>
          <label className="ledger__checkbox">
            <input type="checkbox" checked={includeStress} onChange={(event) => {
                setLoading(true);
                setIncludeStress(event.target.checked);
              }} />
            Include stress-test postings
          </label>
          <span className="ledger__count mono">{rows.length} postings</span>
        </div>

        {error && (
          <p className="ledger__error" role="alert">
            {error}
          </p>
        )}

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
                        className={posting.id === selected?.id ? 'ledger__row--selected' : undefined}
                        {...selectableRow(posting.id === selected?.id, () => setSelectedId(posting.id))}
                      >
                        <td className="mono ledger__id">{posting.id.slice(0, 8)}</td>
                        <td>
                          <div className="ledger__desc">{posting.description}</div>
                          <div className="ledger__desc-sub mono" title={posting.idempotencyKey}>
                            {posting.idempotencyKey}
                          </div>
                        </td>
                        <td className="ledger__amount-cell">
                          <div className={`mono ledger__amount${posting.status === 'reversed' ? ' ledger__amount--struck' : ''}`}>
                            {posting.amount}
                          </div>
                          <StatusPill variant={pill.variant}>{pill.label}</StatusPill>
                        </td>
                        <td className="mono ledger__created">{formatUtc(posting.createdAt)}</td>
                        <td>
                          <StatusPill variant={chip.variant}>{chip.label}</StatusPill>
                        </td>
                      </tr>
                    );
                  })}
                  {!loading && rows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="ledger__empty">
                        No postings match. Approve a fee correction in Review, or post through the API.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="ledger__table-foot">
              <span>
                {loading ? 'Loading…' : `Showing ${rows.length} postings`}
                {nextCursor && !loading && (
                  <>
                    {' · '}
                    <button type="button" className="ledger__link-btn" onClick={() => {
                        setLoading(true);
                        void load(nextCursor);
                      }}>
                      Load more
                    </button>
                  </>
                )}
              </span>
              <span className="ledger__invariant">
                <CheckIcon size={13} /> Every posting balances — debits = credits enforced by a database constraint
              </span>
            </div>
          </div>

          {selected ? (
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
              <div className={`ledger__detail-amount mono${selected.status === 'reversed' ? ' ledger__amount--struck' : ''}`}>
                {selected.amount}
              </div>
              <div className="ledger__detail-meta">
                <StatusPill variant={STATUS_PILL[selected.status].variant}>{STATUS_PILL[selected.status].label}</StatusPill>
                <span className="mono">Created {formatUtcFull(selected.createdAt)}</span>
              </div>

              <section className="ledger__detail-section">
                <div className="ledger__detail-section-head">
                  <span>Journal entries</span>
                  <StatusPill variant={selected.balanced ? 'success' : 'error'}>
                    {selected.balanced ? 'Balanced' : 'Unbalanced'}
                  </StatusPill>
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
                    {selected.lines.map((line, index) => (
                      <tr key={index}>
                        <td>{line.account}</td>
                        <td className="num mono">{line.debit ?? '—'}</td>
                        <td className="num mono">{line.credit ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td>Total</td>
                      <td className="num mono">{selected.debitTotal}</td>
                      <td className="num mono">{selected.creditTotal}</td>
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
                  Replaying this key returns this same posting. Same key with a different payload is rejected (409).
                </p>
              </section>

              {selected.source === 'ai_tool' && (
                <section className="ledger__detail-section">
                  <div className="ledger__detail-section-head">
                    <span>AI provenance</span>
                  </div>
                  <Provenance postingId={selected.id} />
                </section>
              )}

              <div className="ledger__detail-actions">
                {selected.reversedBy ? (
                  <button type="button" className="ledger__link-btn" onClick={() => setSelectedId(selected.reversedBy)}>
                    Reversed by {selected.reversedBy.slice(0, 8)} →
                  </button>
                ) : selected.status === 'reversal' ? (
                  <Link to={`/ledger?posting=${selected.reverses}`} onClick={() => setSelectedId(selected.reverses)}>
                    Reverses {selected.reverses?.slice(0, 8)} →
                  </Link>
                ) : (
                  <ReverseAction
                    key={selected.id}
                    posting={selected}
                    onReversed={(reversalId) => {
                      setSelectedId(reversalId);
                      void load();
                    }}
                  />
                )}
              </div>
            </aside>
          ) : (
            <aside className="panel ledger__detail-panel">
              <p className="ledger__help">{loading ? 'Loading…' : 'Select a posting to see its journal entries.'}</p>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
