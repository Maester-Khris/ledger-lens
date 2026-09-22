import type { Screen } from '../App';
import { ChatIcon, DashboardIcon, DocumentsIcon, LedgerIcon } from './Icons';
import './Sidebar.css';

type NavItem = {
  id: Screen;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
};

const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: DashboardIcon },
  { id: 'chat', label: 'Chat', icon: ChatIcon },
  { id: 'documents', label: 'Documents', icon: DocumentsIcon },
  { id: 'ledger', label: 'Ledger', icon: LedgerIcon },
];

type SidebarProps = {
  active: Screen;
  onNavigate: (screen: Screen) => void;
};

export function Sidebar({ active, onNavigate }: SidebarProps) {
  return (
    <nav className="sidebar">
      <div className="sidebar__brand">
        <span className="sidebar__brand-mark" aria-hidden="true" />
        <span className="sidebar__brand-name">Ledger Assistant</span>
        <span className="sidebar__brand-tag mono">Demo</span>
      </div>

      <div className="sidebar__section-label mono">Navigation</div>

      <ul className="sidebar__nav">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = item.id === active;
          return (
            <li key={item.id}>
              <button
                type="button"
                className={`sidebar__nav-item${isActive ? ' sidebar__nav-item--active' : ''}`}
                onClick={() => onNavigate(item.id)}
                aria-current={isActive ? 'page' : undefined}
              >
                <Icon size={18} />
                <span className="sidebar__nav-label">{item.label}</span>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="sidebar__footer">
        <div className="sidebar__footer-name">Demo workspace</div>
        <div className="sidebar__footer-role mono">
          <span className="sidebar__status-dot" aria-hidden="true" /> API connected
        </div>
      </div>
    </nav>
  );
}
