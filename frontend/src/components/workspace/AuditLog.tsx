import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { LANGFUSE_URL, type ToolInvocationDto, listToolInvocations } from '../../api';
import { RefreshButton } from './RefreshButton';

interface AuditLogProps {
  sessionId: string;
  refreshKey: number;  // bumped by Chat after every finished turn
}

export function AuditLog({ sessionId, refreshKey }: AuditLogProps) {
  const [rows, setRows] = useState<ToolInvocationDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    listToolInvocations({ sessionId, limit: 200 })
      .then((r) => { setRows(r); setError(null); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load the audit trail'))
      .finally(() => setBusy(false));
  }, [sessionId]);

  useEffect(load, [load, refreshKey]);

  return (
    <div>
      <div className="ws-pane__head"><h3>Audit trail</h3><RefreshButton onClick={load} busy={busy} /></div>
      {error && <p className="ws-error">{error}</p>}
      {!error && rows === null && <p className="ws-empty">Loading…</p>}
      {rows?.length === 0 && <p className="ws-empty">No AI decisions in this conversation yet.</p>}
      <ol className="ws-audit">
        {rows?.map((r) => (
          <li key={r.id}>
            <div><strong>{r.tool_name}</strong> · {new Date(r.created_at).toLocaleTimeString()}</div>
            <div className="ws-reason">{r.model_id} · prompt {r.prompt_version}</div>
            <pre className="ws-input">{JSON.stringify(Object.fromEntries(Object.entries(r.input).filter(([k]) => k !== 'turn_id')), null, 1)}</pre>
            {r.decision
              ? <div>{r.decision.decision} by {r.decision.decided_by}
                  {r.decision.posting_id && <> · <Link to={`/ledger?posting=${r.decision.posting_id}`}>View posting →</Link></>}</div>
              : r.approval_required && <Link to="/review#approvals">Awaiting approval →</Link>}
            {r.trace_id && LANGFUSE_URL && (
              <a href={`${LANGFUSE_URL}/traces/${r.trace_id}`} target="_blank" rel="noreferrer">View trace →</a>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
