import { RefreshIcon } from '../Icons';

interface RefreshButtonProps {
  onClick(): void;
  busy: boolean;
}

export function RefreshButton({ onClick, busy }: RefreshButtonProps) {
  return (
    <button type="button" className="ws-refresh" onClick={onClick} disabled={busy} aria-label={busy ? 'Refreshing' : 'Refresh'}>
      <RefreshIcon size={14} className={busy ? 'ws-refresh__icon ws-refresh__icon--spin' : 'ws-refresh__icon'} />
    </button>
  );
}
