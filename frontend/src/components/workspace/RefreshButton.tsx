import { RefreshIcon } from '../Icons';

interface RefreshButtonProps {
  onClick(): void;
  busy: boolean;
}

export function RefreshButton({ onClick, busy }: RefreshButtonProps) {
  return (
    <button type="button" className="ws-refresh" onClick={onClick} disabled={busy} aria-label="Refresh">
      <RefreshIcon size={13} className={busy ? 'ws-refresh__icon ws-refresh__icon--spin' : 'ws-refresh__icon'} />
      {busy ? 'Refreshing…' : 'Refresh'}
    </button>
  );
}
