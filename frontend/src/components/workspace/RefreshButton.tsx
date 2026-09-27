interface RefreshButtonProps {
  onClick(): void;
  busy: boolean;
}

export function RefreshButton({ onClick, busy }: RefreshButtonProps) {
  return (
    <button type="button" className="ws-refresh" onClick={onClick} disabled={busy} aria-label="Refresh">
      {busy ? 'Refreshing…' : 'Refresh'}
    </button>
  );
}
