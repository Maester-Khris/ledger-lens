import { useEffect, useState } from 'react';
import { type TermsDto, getTerms } from '../../api';

function percent(bps: string): string {
  return `${(Number(bps) / 100).toFixed(2)}%`;
}

interface BillingReconciliationProps {
  documentId: string;
}

export function BillingReconciliation({ documentId }: BillingReconciliationProps) {
  const [terms, setTerms] = useState<TermsDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTerms(null);
    setError(null);
    getTerms(documentId).then(setTerms).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load billing reconciliation'));
  }, [documentId]);

  if (error) return <p className="ws-error">{error}</p>;
  if (!terms) return <p className="ws-empty">Loading…</p>;
  if (!terms.household) return <p className="ws-empty">Not linked to a billing household.</p>;

  return (
    <div className="ws-billing">
      <div className="ws-pane__intro">
        <p className="ws-pane__meta">Household <strong>{terms.household.name}</strong></p>
      </div>
      {terms.billing_schedule ? (
        <dl className="ws-field">
          <dt className="ws-field__label">
            <span>Billing schedule</span>
            <span className="ws-badge mono">v{terms.billing_schedule.version} ({terms.billing_schedule.method})</span>
          </dt>
          <dd className="ws-field__value">
            <span className="ws-field__value-text ws-field__value-text--lg">
              {terms.billing_schedule.tiers.map((t) => percent(t.rate_bps)).join(' / ')}
            </span>
          </dd>
        </dl>
      ) : <p className="ws-empty">No billing schedule in effect today.</p>}
    </div>
  );
}
