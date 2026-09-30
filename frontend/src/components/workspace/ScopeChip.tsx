interface ScopeChipProps {
  title: string | null;
  onOpen(): void;
  onClear(): void;
}

export function ScopeChip({ title, onOpen, onClear }: ScopeChipProps) {
  return (
    <div className="ws-chip">
      <button type="button" className="ws-chip__label" onClick={onOpen}>
        {title ? <>Scoped to: <strong>{title}</strong></> : 'All documents'}
      </button>
      {title && (
        <button type="button" className="ws-chip__clear" onClick={onClear} aria-label="Clear the document scope">✕</button>
      )}
    </div>
  );
}
