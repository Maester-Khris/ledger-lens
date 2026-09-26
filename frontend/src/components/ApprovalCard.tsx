import { useState } from 'react';
import { Link } from 'react-router';
import { type ToolDecisionDto, type ToolInvocationDto, decideToolInvocation } from '../api';
import { formatMinor } from '../lib/money';
import { formatUtc } from '../lib/time';
import { StatusPill } from './StatusPill';
import './ApprovalCard.css';

interface ApprovalCardProps {
  invocation: ToolInvocationDto;
  onDecided?: (decision: ToolDecisionDto) => void;
}

export function ApprovalCard({ invocation, onDecided }: ApprovalCardProps) {
  const [decision, setDecision] = useState<ToolDecisionDto | null>(invocation.decision);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const entries = invocation.proposed_entries ?? [];
  const result =
    invocation.result_amount_minor !== null && invocation.result_currency
      ? formatMinor(invocation.result_amount_minor, invocation.result_currency)
      : '—';

  const decide = async (choice: 'approved' | 'rejected') => {
    setSubmitting(true);
    setError(null);
    try {
      const recorded = await decideToolInvocation(invocation.id, choice);
      setDecision(recorded);
      onDecided?.(recorded);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The decision was not recorded');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="tool-card">
      <div className="tool-card__head">
        <span className="tool-card__name mono">{invocation.tool_name}</span>
        {decision === null ? (
          <StatusPill variant="warning">Awaiting approval</StatusPill>
        ) : (
          <StatusPill variant={decision.decision === 'approved' ? 'success' : 'neutral'}>
            {decision.decision === 'approved' ? 'Approved' : 'Rejected'}
          </StatusPill>
        )}
      </div>
      <dl className="tool-card__facts">
        <div>
          <dt>Result</dt>
          <dd className="mono tool-card__result">{result}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd className="mono">{invocation.model_id}</dd>
        </div>
        <div>
          <dt>Session</dt>
          <dd className="mono">{invocation.session_id}</dd>
        </div>
        <div>
          <dt>Proposed</dt>
          <dd className="mono">{formatUtc(invocation.created_at)}</dd>
        </div>
      </dl>
      <div className="tool-card__section">
        <div className="tool-card__section-head">Proposed journal entry</div>
        <table className="tool-card__table">
          <thead>
            <tr>
              <th>Account</th>
              <th className="num">Debit</th>
              <th className="num">Credit</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => (
              <tr key={index}>
                <td>{entry.account_name}</td>
                <td className="num mono">{entry.direction === 'debit' ? formatMinor(entry.amount, entry.currency) : '—'}</td>
                <td className="num mono">{entry.direction === 'credit' ? formatMinor(entry.amount, entry.currency) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="tool-card__actions">
        {decision === null ? (
          <>
            <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void decide('approved')}>
              Approve and post
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => void decide('rejected')}>
              Reject
            </button>
            <span className="tool-card__help">Approving posts exactly these entries to the ledger, once.</span>
          </>
        ) : decision.posting_id ? (
          <span className="tool-card__posted">
            Posted · <Link to={`/ledger?posting=${decision.posting_id}`}>View in ledger →</Link>
          </span>
        ) : (
          <span className="tool-card__help">Rejected by {decision.decided_by}. Nothing was posted.</span>
        )}
        {error && (
          <span className="tool-card__error" role="alert">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
