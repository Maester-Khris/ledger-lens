import { useEffect, useState } from 'react';
import { type TermFieldDto, type TermsDto, documentPageUrl, getTerms } from '../../api';

const GROUPS: { id: string; label: string }[] = [
  { id: 'parties', label: 'Parties' },
  { id: 'fee_schedule', label: 'Fee schedule' },
  { id: 'billing_terms', label: 'Billing terms' },
  { id: 'term_and_law', label: 'Term and governing law' },
  { id: 'other', label: 'Other' },
];
const STATUS_LABEL: Record<TermFieldDto['status'], string> = {
  accepted: 'Accepted', confirmed: 'Confirmed', corrected: 'Corrected', rejected: 'Rejected', needs_review: 'Awaiting review',
};
const COMING_SOON_LABEL: Record<string, string> = {
  fee_schedule_history: 'Fee schedule version history', client_type: 'Client type', exceptions: 'Exceptions',
  referral_arrangements: 'Referral arrangements', expense_allocation: 'Expense allocation',
};

interface ContractProfileProps {
  documentId: string;
}

function display(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') {
    const band = value as { band_text?: string; rate_text?: string };
    if (band.band_text || band.rate_text) return [band.band_text, band.rate_text].filter(Boolean).join(' · ');
    return JSON.stringify(value);
  }
  return String(value);
}

function percent(bps: string): string {
  return `${(Number(bps) / 100).toFixed(2)}%`;
}

export function ContractProfile({ documentId }: ContractProfileProps) {
  const [terms, setTerms] = useState<TermsDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTerms(null);
    setError(null);
    getTerms(documentId).then(setTerms).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load the terms'));
  }, [documentId]);

  if (error) return <p className="ws-error">{error}</p>;
  if (!terms) return <p className="ws-empty">Loading the contract profile…</p>;
  if (!terms.extraction) return <p className="ws-empty">Not extracted yet.</p>;
  const fields = terms.extraction.fields;
  return (
    <div className="ws-profile">
      <p className="ws-reason">Every field here traces to a page in the source agreement.</p>
      {GROUPS.map((group) => {
        const rows = fields.filter((f) => f.group === group.id);
        if (rows.length === 0) return null;
        return (
          <section key={group.id}>
            <h3>{group.label}</h3>
            <dl>
              {rows.map((f) => (
                <div key={f.path} className="ws-field">
                  <dt className="ws-field__label">{f.label} <span className={`ws-badge ws-badge--${f.status}`}>{STATUS_LABEL[f.status]}</span></dt>
                  <dd className="ws-field__value">
                    <span className="ws-field__value-text">{display(f.value)}</span>
                    {f.reason && <p className="ws-field__reason">{f.reason}</p>}
                    {f.page !== null && (
                      <a className="ws-field__page" href={documentPageUrl(terms.document_id, terms.version, f.page)} target="_blank" rel="noreferrer">
                        Page {f.page} →
                      </a>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        );
      })}
      <section>
        <h3>Billing reconciliation</h3>
        {terms.household ? (
          <p>
            Household <strong>{terms.household.name}</strong>
            {terms.billing_schedule
              ? <> — billed on schedule v{terms.billing_schedule.version} ({terms.billing_schedule.method}):{' '}
                  {terms.billing_schedule.tiers.map((t) => percent(t.rate_bps)).join(' / ')}</>
              : ' — no billing schedule in effect today.'}
          </p>
        ) : <p className="ws-empty">Not linked to a billing household.</p>}
      </section>
      <section className="ws-muted" aria-disabled="true">
        <h3>Coming soon</h3>
        <ul>
          {terms.coming_soon.map((id) => (
            <li key={id}>{COMING_SOON_LABEL[id] ?? id} <span className="ws-badge">Coming soon</span></li>
          ))}
        </ul>
      </section>
    </div>
  );
}
