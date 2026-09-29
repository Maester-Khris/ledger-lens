import { type ReactNode, useState } from 'react';

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
  return (
    <aside className="ws-panel" aria-label="Document details">
      <div className="ws-panel__head">
        <label className="ws-panel__select-label" htmlFor="ws-panel-select">Viewing</label>
        <select
          id="ws-panel-select"
          className="ws-panel__select"
          value={active.id}
          onChange={(event) => setActiveId(event.target.value)}
        >
          {tabs.map((t) => (
            <option key={t.id} value={t.id}>{t.label}</option>
          ))}
        </select>
      </div>
      <div className="ws-pane">
        {active.content}
      </div>
    </aside>
  );
}
