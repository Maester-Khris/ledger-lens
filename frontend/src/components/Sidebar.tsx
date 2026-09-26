import { NavLink } from 'react-router';
import { type ApiHealth, useApiHealth } from '../lib/useApiHealth';
import { ChatIcon, CheckIcon, DashboardIcon, DocumentsIcon, LedgerIcon } from './Icons';
import './Sidebar.css';

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
};

const NAV_ITEMS: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: DashboardIcon },
  { to: '/review', label: 'Review', icon: CheckIcon },
  { to: '/chat', label: 'Chat', icon: ChatIcon },
  { to: '/documents', label: 'Documents', icon: DocumentsIcon },
  { to: '/ledger', label: 'Ledger', icon: LedgerIcon },
];

const HEALTH_LABEL: Record<ApiHealth, string> = {
  checking: 'Checking API…',
  connected: 'API connected',
  unreachable: 'API unreachable',
};

export function Sidebar() {
  const health = useApiHealth();
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
          return (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  `sidebar__nav-item${isActive ? ' sidebar__nav-item--active' : ''}`
                }
              >
                <Icon size={18} />
                <span className="sidebar__nav-label">{item.label}</span>
              </NavLink>
            </li>
          );
        })}
      </ul>

      <div className="sidebar__footer">
        <div className="sidebar__footer-name">Demo workspace</div>
        <div className="sidebar__footer-role mono" role="status">
          <span className={`sidebar__status-dot sidebar__status-dot--${health}`} aria-hidden="true" /> {HEALTH_LABEL[health]}
        </div>
      </div>
    </nav>
  );
}
