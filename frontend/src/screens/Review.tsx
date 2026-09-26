import { useCallback, useEffect, useState } from 'react';
import {
  type ReviewDecision,
  type ReviewItemDto,
  type ToolInvocationDto,
  documentPageUrl,
  listReviews,
  listToolInvocations,
  submitReview,
} from '../api';
import { ApprovalCard } from '../components/ApprovalCard';
import { formatValue, parseCorrection, reviewReasons } from '../lib/review';
import './Review.css';

interface FieldReviewCardProps {
  item: ReviewItemDto;
  onDone: () => void;
}

function FieldReviewCard({ item, onDone }: FieldReviewCardProps) {
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
    <article className="field-card">
      <div className="field-card__head">
        <span className="field-card__path mono">{item.field_path}</span>
        <span className="field-card__doc">
          {item.document_title} · v{item.version}
          {item.page !== null && ` · p.${item.page}`}
        </span>
        <a href={documentPageUrl(item.document_id, item.version, item.page)} target="_blank" rel="noreferrer">
          Open page →
        </a>
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
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([listReviews(), listToolInvocations({ pending: true })])
      .then(([reviewItems, pending]) => {
        setItems(reviewItems);
        setApprovals(pending);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="review">
      <div className="review__topbar">
        <span>Review</span>
      </div>
      <div className="review__body">
        <h1 className="review__title">Review</h1>
        <p className="review__subtitle">
          Decisions made here are recorded append-only with your name and the time. Nothing below reaches the assistant
          or the ledger until someone decides.
        </p>
        {error && (
          <p className="review__error" role="alert">
            {error}
          </p>
        )}

        <section className="review__section">
          <h2 className="review__section-title">Extracted fields to review ({items?.length ?? '…'})</h2>
          <p className="review__hint">
            The extractor held these back because it could not ground the quote, a validator failed, or the page was hard
            to read. The assistant does not use them until you confirm or correct them.
          </p>
          {items === null ? (
            <p className="review__empty">Loading…</p>
          ) : items.length === 0 ? (
            <p className="review__empty">No fields are waiting. Every extracted field is either accepted or decided.</p>
          ) : (
             <div className="review__list">
              {items.map((item) => (
                <FieldReviewCard key={`${item.run_id}:${item.field_path}`} item={item} onDone={load} />
              ))}
            </div>
          )}
        </section>

        <section className="review__section" id="approvals">
          <h2 className="review__section-title">Fee corrections to approve ({approvals?.length ?? '…'})</h2>
          <p className="review__hint">
            Proposed by the assistant when a contract's fee schedule and billing disagree. Approving posts exactly the
            entries shown.
          </p>
          {approvals === null ? (
            <p className="review__empty">Loading…</p>
          ) : approvals.length === 0 ? (
            <p className="review__empty">No corrections are waiting. Ask the assistant to compare a contract with billing.</p>
          ) : (
            <div className="review__list">
              {approvals.map((invocation) => (
                <ApprovalCard key={invocation.id} invocation={invocation} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
