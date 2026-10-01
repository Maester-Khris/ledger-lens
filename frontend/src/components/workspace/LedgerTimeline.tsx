import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { type TimelineItemDto, getTimeline } from '../../api';
import { RefreshButton } from './RefreshButton';

const KIND_LABEL: Record<TimelineItemDto['kind'], string> = {
  ingested: 'Ingested', extracted: 'Extracted', reviewed: 'Reviewed',
  ai_proposed: 'AI proposed', decided: 'Decided', posted: 'Posted',
};

interface LedgerTimelineProps {
  documentId: string;
  refreshKey: number;
}

function money(minor: number, currency: string): string {
  return new Intl.NumberFormat('en-CA', { style: 'currency', currency }).format(minor / 100);
}

export function LedgerTimeline({ documentId, refreshKey }: LedgerTimelineProps) {
  const [items, setItems] = useState<TimelineItemDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    getTimeline(documentId)
      .then((r) => { setItems(r); setError(null); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load the timeline'))
      .finally(() => setBusy(false));
  }, [documentId]);

  useEffect(load, [load, refreshKey]);

  return (
    <div>
      <div className="ws-pane__head"><h3>From contract to ledger</h3><RefreshButton onClick={load} busy={busy} /></div>
      {error && <p className="ws-error">{error}</p>}
      {!error && items === null && <p className="ws-empty">Loading…</p>}
      {items?.length === 0 && <p className="ws-empty">Nothing has happened to this document yet.</p>}
      <ol className="ws-timeline">
        {items?.map((item, index) => (
          <li key={`${item.at}-${index}`} className={`ws-timeline__item ws-timeline__item--${item.kind}`}>
            <div><span className={`ws-badge ws-badge--${item.kind}`}>{KIND_LABEL[item.kind]}</span> {item.title}</div>
            <div className="ws-reason">{new Date(item.at).toLocaleString()}</div>
            {item.kind === 'decided' && item.detail.recorded === false && (
              <div className="ws-reason">Demo decision, not recorded</div>
            )}
            {item.detail.entries && (
              <details>
                <summary>Entries</summary>
                <ul>
                  {item.detail.entries.map((e, i) => (
                    <li key={i}>{e.direction === 'debit' ? 'Dr' : 'Cr'} {e.account} {money(e.amount_minor, e.currency)}</li>
                  ))}
                </ul>
              </details>
            )}
            {item.links.ledger && <Link to={item.links.ledger}>View in ledger →</Link>}
          </li>
        ))}
      </ol>
    </div>
  );
}
