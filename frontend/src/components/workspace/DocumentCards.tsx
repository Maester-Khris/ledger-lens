import type { DocumentSummary } from '../../api';

interface DocumentCardsProps {
  documents: DocumentSummary[];
  selectedId: string | null;
  onSelect(id: string | null): void;
}

export function DocumentCards({ documents, selectedId, onSelect }: DocumentCardsProps) {
  const ready = documents.filter((d) => d.status === 'ready');
  if (ready.length === 0) return <p className="ws-empty">No indexed contracts yet.</p>;
  return (
    <div className="ws-cards" role="list" aria-label="Choose a contract to ask about">
      {ready.map((d) => {
        const selected = d.id === selectedId;
        return (
          <button key={d.id} type="button" role="listitem" aria-pressed={selected}
                  className={`ws-card${selected ? ' ws-card--selected' : ''}`}
                  onClick={() => onSelect(selected ? null : d.id)}>
            <span className="ws-card__title">{d.title}</span>
            {d.description && <span className="ws-card__description">{d.description}</span>}
            <span className="ws-card__meta">{d.page_count} pages · v{d.version}</span>
          </button>
        );
      })}
    </div>
  );
}
