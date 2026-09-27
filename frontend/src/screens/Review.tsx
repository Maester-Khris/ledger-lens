import { Suspense, useCallback, useEffect, useState } from 'react';
import {
  type DocumentSummary,
  type ReviewDecision,
  type ReviewItemDto,
  type ToolInvocationDto,
  listDocuments,
  listReviews,
  listToolInvocations,
  submitReview,
} from '../api';
import { ApprovalCard } from '../components/ApprovalCard';
import { DocumentViewer } from '../components/DocumentViewer';
import { Pager } from '../components/Pager';
import { paginate } from '../lib/paginate';
import {
  type ViewerTarget,
  approvalTarget,
  fieldTarget,
  formatValue,
  parseCorrection,
  reviewReasons,
} from '../lib/review';
import './Review.css';

const PAGE_SIZE = 5;

interface FieldReviewCardProps {
  item: ReviewItemDto;
  selected: boolean;
  onSelect: () => void;
  onDone: () => void;
}

function FieldReviewCard({ item, selected, onSelect, onDone }: FieldReviewCardProps) {
  const [correcting, setCorrecting] = useState(false);
  const [draft, setDraft] = useState(formatValue(item.value));
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (decision: ReviewDecision) => {
    const corrected = decision === 'corrected' ? parseCorrection(draft) : null;
    if (decision === 'corrected' && corrected === undefined) {
      setError('Enter the corrected value.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await submitReview({
        run_id: item.run_id,
        field_path: item.field_path,
        decision,
        corrected_value: corrected ?? null,
        reason: reason.trim() || null,
      });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The decision was not recorded');
      setSubmitting(false);
    }
  };

  return (
    <article className={`field-card${selected ? ' field-card--selected' : ''}`}>
      <div className="field-card__head">
        <span className="field-card__path mono">{item.field_path}</span>
        <span className="field-card__doc">
          {item.document_title} · v{item.version}
          {item.page !== null && ` · p.${item.page}`}
        </span>
        <button type="button" className="field-card__show" aria-pressed={selected} onClick={onSelect}>
          {selected ? 'Showing' : `Show ${item.page !== null ? `page ${item.page}` : 'document'}`}
        </button>
      </div>
      <dl className="field-card__facts">
        <dt>Extracted value</dt>
        <dd className="mono">{formatValue(item.value)}</dd>
        <dt>Quote</dt>
        <dd className="field-card__quote">“{item.quote}”</dd>
      </dl>
      <ul className="field-card__reasons">
        {reviewReasons(item).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {correcting && (
        <div className="field-card__correct">
          <label>
            Corrected value
            <input className="mono" value={draft} onChange={(event) => setDraft(event.target.value)} />
          </label>
          <label>
            Reason (optional)
            <input value={reason} onChange={(event) => setReason(event.target.value)} />
          </label>
        </div>
      )}
      <div className="field-card__actions">
        {correcting ? (
          <>
            <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void send('corrected')}>
              Save correction
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => setCorrecting(false)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void send('confirmed')}>
              Confirm value
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => setCorrecting(true)}>
              Correct
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => void send('rejected')}>
              Reject
            </button>
          </>
        )}
        {error && (
          <span className="field-card__error" role="alert">
            {error}
          </span>
        )}
      </div>
    </article>
  );
}

export function Review() {
  const [items, setItems] = useState<ReviewItemDto[] | null>(null);
  const [approvals, setApprovals] = useState<ToolInvocationDto[] | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fieldPage, setFieldPage] = useState(1);
  const [approvalPage, setApprovalPage] = useState(1);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([listReviews(), listToolInvocations({ pending: true }), listDocuments()])
      .then(([reviewItems, pending, docs]) => {
        setItems(reviewItems);
        setApprovals(pending);
        setDocuments(docs);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const fields = paginate(items ?? [], fieldPage, PAGE_SIZE);
  const corrections = paginate(approvals ?? [], approvalPage, PAGE_SIZE);

  // Everything the viewer can show, in list order; the first one is shown until the reviewer picks another.
  const targets: ViewerTarget[] = [
    ...(items ?? []).map(fieldTarget),
    ...(approvals ?? []).flatMap((invocation) => approvalTarget(invocation, documents) ?? []),
  ];
  const selected = targets.find((t) => t.key === selectedKey) ?? targets[0] ?? null;

  return (
    <div className="review">
      <div className="review__topbar">
        <span>Review</span>
      </div>
      <div className="review__panes">
        <div className="review__list-pane">
          <h1 className="review__title">Review</h1>
          <p className="review__subtitle">
            Every AI decision that reaches this screen is logged in the audit trail. Decisions are recorded append-only
            with your name and the time — nothing reaches the assistant or the ledger until someone decides.
          </p>
          {error && (
            <p className="review__error" role="alert">
              {error}
            </p>
          )}

          <section className="review__section">
            <h2 className="review__section-title">Extraction anomaly queue ({items?.length ?? '…'})</h2>
            <p className="review__hint">
              Held back because the quote couldn't be grounded, a validator failed, or the page was hard to read.
            </p>
            {items === null ? (
              <p className="review__empty">Loading…</p>
            ) : items.length === 0 ? (
              <p className="review__empty">No fields are waiting. Every extracted field is either accepted or decided.</p>
            ) : (
              <>
                <div className="review__list">
                  {fields.items.map((item) => {
                    const target = fieldTarget(item);
                    return (
                      <FieldReviewCard
                        key={target.key}
                        item={item}
                        selected={selected?.key === target.key}
                        onSelect={() => setSelectedKey(target.key)}
                        onDone={load}
                      />
                    );
                  })}
                </div>
                <Pager page={fields.page} pageCount={fields.pageCount} onChange={setFieldPage} label="Fields pages" />
              </>
            )}
          </section>

          <section className="review__section" id="approvals">
            <h2 className="review__section-title">Fee corrections to approve ({approvals?.length ?? '…'})</h2>
            <p className="review__hint">
              Proposed when billing reconciliation finds a gap between the contract and what's billed. Approving posts exactly the entries shown.
            </p>
            {approvals === null ? (
              <p className="review__empty">Loading…</p>
            ) : approvals.length === 0 ? (
              <p className="review__empty">No corrections are waiting. Ask the assistant to reconcile a contract with billing.</p>
            ) : (
              <>
                <div className="review__list">
                  {corrections.items.map((invocation) => {
                    const target = approvalTarget(invocation, documents);
                    return (
                      <div
                        key={invocation.id}
                        className={`review__approval${target && selected?.key === target.key ? ' review__approval--selected' : ''}`}
                      >
                        {target && (
                          <button
                            type="button"
                            className="field-card__show review__approval-show"
                            aria-pressed={selected?.key === target.key}
                            onClick={() => setSelectedKey(target.key)}
                          >
                            {selected?.key === target.key ? 'Showing contract' : 'Show contract'}
                          </button>
                        )}
                        <ApprovalCard invocation={invocation} />
                      </div>
                    );
                  })}
                </div>
                <Pager
                  page={corrections.page}
                  pageCount={corrections.pageCount}
                  onChange={setApprovalPage}
                  label="Corrections pages"
                />
              </>
            )}
          </section>
        </div>

        <aside className="review__viewer-pane" aria-label="Document viewer">
          {selected ? (
            <Suspense fallback={<p className="review__empty review__viewer-empty">Loading viewer…</p>}>
              <DocumentViewer
                documentId={selected.documentId}
                version={selected.version}
                page={selected.page}
                title={selected.title}
              />
            </Suspense>
          ) : (
            <p className="review__empty review__viewer-empty">Nothing to show — the review queue is empty.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
