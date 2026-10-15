import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { LANGFUSE_URL, type ToolInvocationDto, listToolInvocations } from '../../api';
import { toolLabel } from '../../lib/toolLabels';
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
      <div className="ws-pane__intro">
        <h3 className="ws-pane__meta">Audit trail</h3>
        <p className="ws-pane__desc">Every AI decision that touched this conversation, logged: tool, model, inputs and the human decision.</p>
      </div>
      <RefreshButton onClick={load} busy={busy} />
      {error && <p className="ws-error">{error}</p>}
      {!error && rows === null && <p className="ws-empty">Loading…</p>}
      {rows?.length === 0 && <p className="ws-empty">No AI decisions in this conversation yet.</p>}
      <ol className="ws-timeline">
        {rows?.map((r) => (
          <li key={r.id} className={`ws-timeline__item ws-timeline__item--${r.decision?.decision ?? (r.approval_required ? 'pending' : 'logged')}`}>
            <div className="ws-event">
              <div className="ws-event__top">
                <span className="ws-event__title">{toolLabel(r.tool_name)}</span>
                {r.decision && <span className={`ws-badge ws-badge--${r.decision.decision}`}>{r.decision.decision}</span>}
              </div>
              <div className="ws-event__row">
                <span>{r.tool_name}</span>
                <time dateTime={r.created_at}>{new Date(r.created_at).toLocaleTimeString()}</time>
              </div>
              <div className="ws-event__row">{r.model_id} · prompt {r.prompt_version}</div>
              <pre className="ws-input">{JSON.stringify(Object.fromEntries(Object.entries(r.input).filter(([k]) => k !== 'turn_id')), null, 1)}</pre>
              {r.decision
                ? (
                  <div className="ws-event__row ws-event__row--foot">
                    <span>{r.decision.decision} by <strong>{r.decision.decided_by}</strong></span>
                    {r.decision.posting_id && <Link to={`/ledger?posting=${r.decision.posting_id}`}>View posting →</Link>}
                  </div>
                )
                : r.approval_required && <Link to="/review#approvals">Awaiting approval →</Link>}
              {r.trace_id && LANGFUSE_URL && (
                <a href={`${LANGFUSE_URL}/traces/${r.trace_id}`} target="_blank" rel="noreferrer">View trace →</a>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
