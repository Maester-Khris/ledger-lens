import { useEffect, useState } from 'react';
import { checkHealth } from '../api';

export type ApiHealth = 'checking' | 'connected' | 'unreachable';

const HEALTH_POLL_MS = 15000;

export function useApiHealth(intervalMs: number = HEALTH_POLL_MS): ApiHealth {
  const [health, setHealth] = useState<ApiHealth>('checking');

  useEffect(() => {
    let cancelled = false;
    const check = () =>
      checkHealth().then((ok) => {
        if (!cancelled) setHealth(ok ? 'connected' : 'unreachable');
      });
    void check();
    const timer = window.setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [intervalMs]);

  return health;
}
