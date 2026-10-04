import { useEffect, useState } from 'react';
import { type ToolInvocationDto, listToolInvocations } from '../api';
import { formatMinor } from '../lib/money';
import { formatUtc } from '../lib/time';
import { toolLabel } from '../lib/toolLabels';

/** Public demo: this guest's approved AI postings, checked by the ledger but never recorded (spec P2+P9, D3). */
export function DemoPostings() {
  const [approved, setApproved] = useState<ToolInvocationDto[]>([]);

  useEffect(() => {
    let cancelled = false;
    listToolInvocations({ pending: false, limit: 200 })
      .then((rows) => {
        if (!cancelled) setApproved(rows.filter((i) => i.decision?.decision === 'approved' && !i.decision.recorded));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (approved.length === 0) return null;
  return (
    <section className="panel ledger__demo-postings" aria-label="Your demo postings">
      <div className="ledger__detail-section-head">
        <span>Your demo postings (not recorded)</span>
      </div>
      <p className="ledger__help">
        The ledger checked these entries when you approved them. In the public demo nothing is written, and only you see them.
      </p>
      {approved.map((invocation) => (
        <table key={invocation.id} className="ledger__journal">
          <caption>
            {toolLabel(invocation.tool_name)} · approved {invocation.decision ? formatUtc(invocation.decision.decided_at) : ''}
          </caption>
          <thead>
            <tr>
              <th>Account</th>
              <th className="num">Debit</th>
              <th className="num">Credit</th>
            </tr>
          </thead>
          <tbody>
            {(invocation.proposed_entries ?? []).map((entry, index) => (
              <tr key={index}>
                <td>{entry.account_name}</td>
                <td className="num mono">{entry.direction === 'debit' ? formatMinor(entry.amount, entry.currency) : '-'}</td>
                <td className="num mono">{entry.direction === 'credit' ? formatMinor(entry.amount, entry.currency) : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </section>
  );
}
