import { type KeyboardEvent, type ReactNode, useState } from 'react';

export interface PanelTab {
  id: string;
  label: string;
  content: ReactNode;
}

interface DocumentPanelProps {
  tabs: PanelTab[];
}

export function DocumentPanel({ tabs }: DocumentPanelProps) {
  const [activeId, setActiveId] = useState<string | null>(null);
  if (tabs.length === 0) return null;
  const active = tabs.find((t) => t.id === activeId) ?? tabs[0];
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    const index = tabs.indexOf(active);
    const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    setActiveId(next.id);
    document.getElementById(`ws-tab-${next.id}`)?.focus();
  };
  return (
    <aside className="ws-panel" aria-label="Document details">
      <div className="ws-tabs" role="tablist" onKeyDown={move}>
        {tabs.map((t) => (
          <button key={t.id} id={`ws-tab-${t.id}`} type="button" role="tab" aria-selected={t.id === active.id}
                  aria-controls={`ws-pane-${t.id}`} tabIndex={t.id === active.id ? 0 : -1}
                  className="ws-tab" onClick={() => setActiveId(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <div id={`ws-pane-${active.id}`} role="tabpanel" aria-labelledby={`ws-tab-${active.id}`} className="ws-pane">
        {active.content}
      </div>
    </aside>
  );
}
