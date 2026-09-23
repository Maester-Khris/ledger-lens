import { Navigate, Route, Routes } from 'react-router';
import { AppShell } from './components/AppShell';
import { Landing } from './screens/Landing';
import { Dashboard } from './screens/Dashboard';
import { Chat } from './screens/Chat';
import { Documents } from './screens/Documents';
import { Ledger } from './screens/Ledger';

function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/home" element={<Landing />} />
      <Route element={<AppShell />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/ledger" element={<Ledger />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
