import { Outlet } from 'react-router';
import { Sidebar } from './Sidebar';
import './AppShell.css';

export function AppShell() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-shell__content">
        <Outlet />
      </main>
    </div>
  );
}
